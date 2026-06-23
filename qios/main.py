from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from qios.control import (
    ArbitrationDecision,
    PatchLocalArbitrator,
    PhiCache,
    ReplayLedger,
    RollbackAnchorManager,
    SnapshotPackageBuilder,
)
from qios.control.modulation_profile import ModulationProfileGenerator
from qios.models import (
    ExecutionEvent,
    PatchType,
    PipelineOutcome,
    SnapshotPackage,
    TaskRequest,
    TokenState,
)
from qios.patch_runtime import PatchRuntime
from qios.policy_engine import PolicyEngine
from qios.recovery_engine import RecoveryEngine
from qios.scheduler import Scheduler
from qios.state_store import StateStore
from qios.structured_job import StructuredJobGenerator
from qios.token_engine import PhiTokenEngine

app = typer.Typer(name="qios", help="Q-IOS runtime prototype CLI.")
console = Console()


def load_task_request(task_file: Path) -> TaskRequest:
    payload = json.loads(task_file.read_text())
    return TaskRequest.model_validate(payload)


def _increment_metric(control_metrics: dict[str, int], key: str, amount: int = 1) -> None:
    control_metrics[key] = control_metrics.get(key, 0) + amount


def _append_replay_event(
    replay_ledger: ReplayLedger,
    control_metrics: dict[str, int],
    *,
    task_id: str,
    token_id: str,
    event_type: str,
    patch_id: str | None = None,
    token_state: str | None = None,
    message: str = "",
    metadata: dict[str, object] | None = None,
) -> None:
    replay_ledger.append_event(
        task_id=task_id,
        token_id=token_id,
        event_type=event_type,
        patch_id=patch_id,
        token_state=token_state,
        message=message,
        metadata=metadata,
    )
    _increment_metric(control_metrics, "replay_ledger_events")


def _create_rollback_anchor(
    rollback_manager: RollbackAnchorManager,
    control_metrics: dict[str, int],
    *,
    task_id: str,
    token_id: str,
    patch_id: str,
    anchor_type: str,
    token_state: str,
    metadata: dict[str, object] | None = None,
):
    anchor = rollback_manager.create_anchor(
        task_id=task_id,
        token_id=token_id,
        patch_id=patch_id,
        anchor_type=anchor_type,
        token_state=token_state,
        replay_position=len(rollback_manager.list_anchors(token_id)),
        metadata=metadata,
    )
    _increment_metric(control_metrics, "rollback_anchors_created")
    return anchor


def _control_candidate_patches(token) -> list[str]:
    candidates = [
        PatchType.ANALYSIS.value,
        PatchType.SANDBOX.value,
        PatchType.HUMAN_REVIEW.value,
    ]
    if token.fallback:
        candidates.append(token.fallback)
    elif PatchType.FALLBACK.value not in candidates:
        candidates.append(PatchType.FALLBACK.value)

    preferred_patch = token.assigned_patch or token.patch_hint
    if preferred_patch and preferred_patch not in candidates:
        candidates.insert(0, preferred_patch)

    return list(dict.fromkeys(candidates))


def _control_patch_health(token, phi_cache: PhiCache, patch_ids: list[str]) -> dict[str, float]:
    defaults = {
        PatchType.ANALYSIS.value: 0.9 if token.role == "analysis" else 0.82,
        PatchType.SANDBOX.value: 0.92 if token.role == "execution" else 0.84,
        PatchType.FALLBACK.value: 0.74,
        PatchType.HUMAN_REVIEW.value: 0.7,
    }
    health: dict[str, float] = {}

    for patch_id in patch_ids:
        entry = phi_cache.get_entry(patch_id, token.role)
        base_score = defaults.get(patch_id, 0.8)
        health[patch_id] = round(entry.last_health_score if entry.last_health_score is not None else base_score, 3)

    return health


def _control_patch_congestion(patch_ids: list[str]) -> dict[str, float]:
    return {
        patch_id: round(0.02 * index, 3)
        for index, patch_id in enumerate(patch_ids)
    }


def _select_recovery_patch(token, failed_patches: set[str]) -> str:
    candidates = [
        token.fallback,
        PatchType.FALLBACK.value,
        PatchType.SANDBOX.value,
        PatchType.ANALYSIS.value,
        PatchType.HUMAN_REVIEW.value,
    ]
    for candidate in candidates:
        if candidate and candidate not in failed_patches:
            return candidate
    return token.fallback or PatchType.FALLBACK.value


def build_snapshot(
    task_request: TaskRequest,
    token,
    *,
    control_snapshot=None,
    control_metadata: dict[str, object] | None = None,
) -> SnapshotPackage:
    payload = {
        "task": task_request.model_dump(mode="json"),
        "token": token.model_dump(mode="json"),
    }
    if control_snapshot is not None:
        payload["control_plane"] = control_snapshot.model_dump(mode="json")
    if control_metadata:
        payload["control_metadata"] = control_metadata
    return SnapshotPackage(
        task_id=task_request.task_id,
        token_id=token.token_id,
        lifecycle_state=token.lifecycle_state,
        assigned_patch=token.assigned_patch or token.patch_hint,
        phi_modulation=token.phi_modulation,
        payload=payload,
    )


def build_event(
    task_id: str,
    token_id: str,
    state: TokenState,
    event_type: str,
    message: str,
    patch: str | None = None,
    details: dict[str, object] | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        task_id=task_id,
        token_id=token_id,
        state=state,
        event_type=event_type,
        message=message,
        patch=patch,
        details=details or {},
    )


def submit_task_request(
    task_request: TaskRequest,
    state_store: StateStore | None = None,
    *,
    phi_cache: PhiCache | None = None,
    replay_ledger: ReplayLedger | None = None,
    rollback_manager: RollbackAnchorManager | None = None,
) -> PipelineOutcome:
    store = state_store or StateStore()
    generator = StructuredJobGenerator()
    token_engine = PhiTokenEngine()
    policy_engine = PolicyEngine()
    scheduler = Scheduler()
    runtime = PatchRuntime()
    recovery_engine = RecoveryEngine()
    modulation_generator = ModulationProfileGenerator()
    arbitrator = PatchLocalArbitrator()
    snapshot_builder = SnapshotPackageBuilder()
    control_metrics: dict[str, int] = {
        "phi_cache_hits": 0,
        "phi_cache_updates": 0,
        "modulation_profiles_created": 0,
        "arbitration_accepts": 0,
        "arbitration_rejects": 0,
        "arbitration_defers": 0,
        "arbitration_reroutes": 0,
        "snapshots_created": 0,
        "rollback_anchors_created": 0,
        "replay_ledger_events": 0,
        "local_reentry_count": 0,
    }
    control_metadata: dict[str, object] = {}
    cache = phi_cache or PhiCache()
    ledger = replay_ledger or ReplayLedger()
    rollback = rollback_manager or RollbackAnchorManager()

    job = generator.generate(task_request)
    token = token_engine.create_token(job)
    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type="token_created",
        patch_id=token.patch_hint,
        token_state=token.lifecycle_state.value,
        message="Phi-token created from structured job.",
        metadata={"role": token.role, "priority": token.priority},
    )
    initial_anchor = _create_rollback_anchor(
        rollback,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        patch_id=token.patch_hint or PatchType.ANALYSIS.value,
        anchor_type="planned",
        token_state=token.lifecycle_state.value,
        metadata={"objective": task_request.objective},
    )
    initial_control_snapshot = snapshot_builder.build(
        token=token,
        patch_id=token.patch_hint or PatchType.ANALYSIS.value,
        rollback_anchor_id=initial_anchor.anchor_id,
        replay_lineage=ledger.get_replay_lineage(token.token_id),
        memory_isolation_label=token.patch_hint or PatchType.ANALYSIS.value,
        metadata={"phase": "planned"},
    )
    _increment_metric(control_metrics, "snapshots_created")

    store.save_task(task_request)
    store.save_token(token)
    store.save_snapshot(
        build_snapshot(
            task_request,
            token,
            control_snapshot=initial_control_snapshot,
            control_metadata={"latest_anchor_id": initial_anchor.anchor_id},
        )
    )
    store.save_event(
        build_event(
            task_request.task_id,
            token.token_id,
            token.lifecycle_state,
            "token_planned",
            "Task objective converted into a structured phi-token.",
            patch=token.patch_hint,
            details={"structured_job": job.model_dump(mode="json")},
        )
    )

    admissible, reason = policy_engine.check_admissibility(token)
    event_type = "admissibility_passed" if admissible else "admissibility_rejected"
    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type=event_type,
        patch_id=token.patch_hint,
        token_state=token.lifecycle_state.value,
        message=reason,
    )
    store.save_event(
        build_event(
            task_request.task_id,
            token.token_id,
            token.lifecycle_state,
            event_type,
            reason,
            patch=token.patch_hint,
        )
    )
    if not admissible:
        token.lifecycle_state = TokenState.TERMINATED
        store.save_token(token)
        rejection_anchor = _create_rollback_anchor(
            rollback,
            control_metrics,
            task_id=task_request.task_id,
            token_id=token.token_id,
            patch_id=token.patch_hint or PatchType.ANALYSIS.value,
            anchor_type="policy_rejected",
            token_state=token.lifecycle_state.value,
            metadata={"reason": reason},
        )
        rejection_snapshot = snapshot_builder.build(
            token=token,
            patch_id=token.patch_hint or PatchType.ANALYSIS.value,
            rollback_anchor_id=rejection_anchor.anchor_id,
            replay_lineage=ledger.get_replay_lineage(token.token_id),
            memory_isolation_label=token.patch_hint or PatchType.ANALYSIS.value,
            metadata={"phase": "policy_rejected", "reason": reason},
        )
        _increment_metric(control_metrics, "snapshots_created")
        control_metadata.update(
            {
                "latest_anchor_id": rejection_anchor.anchor_id,
                "replay_lineage": ledger.get_replay_lineage(token.token_id),
                "policy_reason": reason,
            }
        )
        store.save_snapshot(
            build_snapshot(
                task_request,
                token,
                control_snapshot=rejection_snapshot,
                control_metadata=control_metadata,
            )
        )
        return PipelineOutcome(
            task_id=task_request.task_id,
            token_id=token.token_id,
            success=False,
            final_state=token.lifecycle_state,
            final_patch=token.patch_hint,
            failure_reason=reason,
            control_metrics=control_metrics,
            control_metadata=control_metadata,
        )

    patch_candidates = _control_candidate_patches(token)
    if any(cache.get_entry(patch_id, token.role).has_history for patch_id in patch_candidates):
        _increment_metric(control_metrics, "phi_cache_hits")
    patch_health = _control_patch_health(token, cache, patch_candidates)
    patch_congestion = _control_patch_congestion(patch_candidates)
    profile = modulation_generator.generate(
        token,
        candidate_patch_ids=patch_candidates,
        phi_cache=cache,
        patch_health=patch_health,
        patch_congestion=patch_congestion,
    )
    _increment_metric(control_metrics, "modulation_profiles_created")
    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type="modulation_profile_generated",
        patch_id=profile.selected_patch_id,
        token_state=token.lifecycle_state.value,
        message="Generated patent-aligned modulation profile.",
        metadata={"scores": [score.model_dump(mode="json") for score in profile.patch_scores]},
    )
    arbitration = arbitrator.arbitrate(
        token,
        profile,
        patch_health=patch_health,
        patch_congestion=patch_congestion,
        quarantined_patches=set(),
    )
    if arbitration.decision == ArbitrationDecision.ACCEPT:
        _increment_metric(control_metrics, "arbitration_accepts")
    elif arbitration.decision == ArbitrationDecision.REJECT:
        _increment_metric(control_metrics, "arbitration_rejects")
    elif arbitration.decision == ArbitrationDecision.DEFER:
        _increment_metric(control_metrics, "arbitration_defers")
    else:
        _increment_metric(control_metrics, "arbitration_reroutes")
    selected_patch = profile.selected_patch_id or token.patch_hint
    if arbitration.decision != ArbitrationDecision.ACCEPT and arbitration.alternative_patch_id is not None:
        selected_patch = arbitration.alternative_patch_id
    if selected_patch is not None:
        token.patch_hint = selected_patch
    control_metadata["initial_arbitration"] = arbitration.model_dump(mode="json")

    scheduler.assign_patch(token)
    assignment_anchor = _create_rollback_anchor(
        rollback,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        patch_id=token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value,
        anchor_type="assigned",
        token_state=token.lifecycle_state.value,
        metadata={"arbitration_decision": arbitration.decision.value},
    )
    assigned_control_snapshot = snapshot_builder.build(
        token=token,
        patch_id=token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value,
        rollback_anchor_id=assignment_anchor.anchor_id,
        replay_lineage=ledger.get_replay_lineage(token.token_id),
        memory_isolation_label=token.assigned_patch or token.patch_hint or "default",
        metadata={"phase": "assigned", "arbitration": arbitration.model_dump(mode="json")},
    )
    _increment_metric(control_metrics, "snapshots_created")
    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type="patch_assigned",
        patch_id=token.assigned_patch,
        token_state=token.lifecycle_state.value,
        message=f"Scheduler assigned token to {token.assigned_patch}.",
    )
    store.save_token(token)
    store.save_snapshot(
        build_snapshot(
            task_request,
            token,
            control_snapshot=assigned_control_snapshot,
            control_metadata={
                "latest_anchor_id": assignment_anchor.anchor_id,
                "replay_lineage": ledger.get_replay_lineage(token.token_id),
                "initial_arbitration": arbitration.model_dump(mode="json"),
            },
        )
    )
    store.save_event(
        build_event(
            task_request.task_id,
            token.token_id,
            token.lifecycle_state,
            "patch_assigned",
            f"Scheduler assigned token to {token.assigned_patch}.",
            patch=token.assigned_patch,
        )
    )

    execution_anchor = _create_rollback_anchor(
        rollback,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        patch_id=token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value,
        anchor_type="pre_execution",
        token_state=token.lifecycle_state.value,
    )
    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type="execution_started",
        patch_id=token.assigned_patch,
        token_state=token.lifecycle_state.value,
        message="Execution dispatched to assigned patch.",
    )
    result = runtime.execute(token)
    active_patch = result.patch or token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value
    if result.success:
        cache.update_success(active_patch, token.role, latency_ms=0.0, health_score=0.92)
        _increment_metric(control_metrics, "phi_cache_updates")
    else:
        cache.update_failure(active_patch, token.role, latency_ms=0.0, health_score=0.62)
        _increment_metric(control_metrics, "phi_cache_updates")
    execution_snapshot = snapshot_builder.build(
        token=token,
        patch_id=active_patch,
        rollback_anchor_id=execution_anchor.anchor_id,
        replay_lineage=ledger.get_replay_lineage(token.token_id),
        memory_isolation_label=active_patch,
        metadata={"phase": "execution_result", "result": result.model_dump(mode="json")},
    )
    _increment_metric(control_metrics, "snapshots_created")
    store.save_token(token)
    store.save_snapshot(
        build_snapshot(
            task_request,
            token,
            control_snapshot=execution_snapshot,
            control_metadata={
                "latest_anchor_id": execution_anchor.anchor_id,
                "replay_lineage": ledger.get_replay_lineage(token.token_id),
                "initial_arbitration": arbitration.model_dump(mode="json"),
            },
        )
    )

    if result.success:
        completion_anchor = _create_rollback_anchor(
            rollback,
            control_metrics,
            task_id=task_request.task_id,
            token_id=token.token_id,
            patch_id=active_patch,
            anchor_type="completed",
            token_state=token.lifecycle_state.value,
        )
        _append_replay_event(
            ledger,
            control_metrics,
            task_id=task_request.task_id,
            token_id=token.token_id,
            event_type="execution_completed",
            patch_id=result.patch,
            token_state=token.lifecycle_state.value,
            message=result.output or "Execution completed.",
        )
        store.save_event(
            build_event(
                task_request.task_id,
                token.token_id,
                token.lifecycle_state,
                "execution_completed",
                result.output or "Execution completed.",
                patch=result.patch,
            )
        )
        control_metadata.update(
            {
                "latest_anchor_id": completion_anchor.anchor_id,
                "replay_lineage": ledger.get_replay_lineage(token.token_id),
                "phi_cache_rankings": cache.rank_patches(patch_candidates, token.role),
            }
        )
        return PipelineOutcome(
            task_id=task_request.task_id,
            token_id=token.token_id,
            success=True,
            final_state=token.lifecycle_state,
            final_patch=result.patch,
            control_metrics=control_metrics,
            control_metadata=control_metadata,
        )

    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type="execution_failed",
        patch_id=result.patch,
        token_state=token.lifecycle_state.value,
        message=result.failure_reason or "Execution failed.",
    )
    store.save_event(
        build_event(
            task_request.task_id,
            token.token_id,
            token.lifecycle_state,
            "execution_failed",
            result.failure_reason or "Execution failed.",
            patch=result.patch,
        )
    )

    failed_patches = ledger.get_failed_patches(token.token_id)
    recovery_target_patch = _select_recovery_patch(token, failed_patches)
    recovery_anchor = _create_rollback_anchor(
        rollback,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        patch_id=active_patch,
        anchor_type="pre_recovery",
        token_state=token.lifecycle_state.value,
        metadata={"failed_patches": sorted(failed_patches)},
    )
    _increment_metric(control_metrics, "local_reentry_count")
    cache.update_reroute(active_patch, token.role)
    _increment_metric(control_metrics, "phi_cache_updates")
    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type="recovery_started",
        patch_id=active_patch,
        token_state=token.lifecycle_state.value,
        message="Recovery engine preparing local reroute.",
        metadata={"rollback_anchor_id": recovery_anchor.anchor_id},
    )
    recovery_engine.recover(
        token,
        result.failure_reason or "Execution failed.",
        rollback_anchor_id=recovery_anchor.anchor_id,
        replay_lineage=ledger.get_replay_lineage(token.token_id),
        failed_patches=sorted(failed_patches),
        alternative_patch=recovery_target_patch,
    )
    recovery_control_snapshot = snapshot_builder.build(
        token=token,
        patch_id=token.assigned_patch or recovery_target_patch,
        rollback_anchor_id=recovery_anchor.anchor_id,
        replay_lineage=ledger.get_replay_lineage(token.token_id),
        memory_isolation_label=token.assigned_patch or recovery_target_patch or "default",
        metadata={"phase": "recovery_assignment"},
    )
    _increment_metric(control_metrics, "snapshots_created")
    store.save_token(token)
    store.save_snapshot(
        build_snapshot(
            task_request,
            token,
            control_snapshot=recovery_control_snapshot,
            control_metadata={
                "latest_anchor_id": recovery_anchor.anchor_id,
                "replay_lineage": ledger.get_replay_lineage(token.token_id),
                "failed_patches": sorted(failed_patches),
            },
        )
    )
    store.save_event(
        build_event(
            task_request.task_id,
            token.token_id,
            token.lifecycle_state,
            "recovery_reassigned",
            f"Recovery rerouted token to {token.assigned_patch}.",
            patch=token.assigned_patch,
            details={"recovery_reason": result.failure_reason},
        )
    )
    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type="recovery_reassigned",
        patch_id=token.assigned_patch,
        token_state=token.lifecycle_state.value,
        message=f"Recovery rerouted token to {token.assigned_patch}.",
    )

    resumed_result = runtime.execute(token)
    resumed_patch = resumed_result.patch or token.assigned_patch or token.patch_hint or PatchType.FALLBACK.value
    if resumed_result.success:
        cache.update_success(resumed_patch, token.role, latency_ms=0.0, health_score=0.85)
        _increment_metric(control_metrics, "phi_cache_updates")
    else:
        cache.update_failure(resumed_patch, token.role, latency_ms=0.0, health_score=0.5)
        _increment_metric(control_metrics, "phi_cache_updates")
    resumed_anchor = _create_rollback_anchor(
        rollback,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        patch_id=resumed_patch,
        anchor_type="resumed_execution",
        token_state=token.lifecycle_state.value,
    )
    resumed_control_snapshot = snapshot_builder.build(
        token=token,
        patch_id=resumed_patch,
        rollback_anchor_id=resumed_anchor.anchor_id,
        replay_lineage=ledger.get_replay_lineage(token.token_id),
        memory_isolation_label=resumed_patch,
        metadata={"phase": "resumed_execution", "result": resumed_result.model_dump(mode="json")},
    )
    _increment_metric(control_metrics, "snapshots_created")
    store.save_token(token)
    store.save_snapshot(
        build_snapshot(
            task_request,
            token,
            control_snapshot=resumed_control_snapshot,
            control_metadata={
                "latest_anchor_id": resumed_anchor.anchor_id,
                "replay_lineage": ledger.get_replay_lineage(token.token_id),
                "failed_patches": sorted(failed_patches),
            },
        )
    )
    _append_replay_event(
        ledger,
        control_metrics,
        task_id=task_request.task_id,
        token_id=token.token_id,
        event_type="execution_resumed_completed" if resumed_result.success else "execution_resumed_failed",
        patch_id=resumed_result.patch,
        token_state=token.lifecycle_state.value,
        message=resumed_result.output or resumed_result.failure_reason or "Execution resumed.",
    )
    store.save_event(
        build_event(
            task_request.task_id,
            token.token_id,
            token.lifecycle_state,
            "execution_resumed_completed" if resumed_result.success else "execution_resumed_failed",
            resumed_result.output or resumed_result.failure_reason or "Execution resumed.",
            patch=resumed_result.patch,
        )
    )
    control_metadata.update(
        {
            "latest_anchor_id": resumed_anchor.anchor_id,
            "replay_lineage": ledger.get_replay_lineage(token.token_id),
            "failed_patches": sorted(failed_patches),
            "phi_cache_rankings": cache.rank_patches(patch_candidates, token.role),
        }
    )

    return PipelineOutcome(
        task_id=task_request.task_id,
        token_id=token.token_id,
        success=resumed_result.success,
        final_state=token.lifecycle_state,
        final_patch=resumed_result.patch,
        recovery_performed=True,
        failure_reason=None if resumed_result.success else resumed_result.failure_reason,
        control_metrics=control_metrics,
        control_metadata=control_metadata,
    )


def render_events(events: list[ExecutionEvent]) -> Table:
    table = Table(title="Execution Events")
    table.add_column("Time")
    table.add_column("Type")
    table.add_column("State")
    table.add_column("Patch")
    table.add_column("Message")

    for event in events:
        table.add_row(
            event.created_at.isoformat(timespec="seconds"),
            event.event_type,
            event.state.value,
            event.patch or "-",
            event.message,
        )
    return table


@app.command()
def submit(task_file: Path = typer.Argument(..., exists=True, readable=True, help="Path to a task JSON file.")) -> None:
    task_request = load_task_request(task_file)
    outcome = submit_task_request(task_request)
    events = StateStore().list_events(task_request.task_id)

    console.print(
        Panel.fit(
            f"Task ID: {outcome.task_id}\n"
            f"Token ID: {outcome.token_id}\n"
            f"Final state: {outcome.final_state.value}\n"
            f"Patch: {outcome.final_patch or '-'}\n"
            f"Recovery: {'yes' if outcome.recovery_performed else 'no'}",
            title="Q-IOS Submission",
        )
    )
    console.print(render_events(events))

    if not outcome.success:
        raise typer.Exit(code=1)


@app.command()
def events(task_id: str = typer.Argument(..., help="Task identifier to inspect.")) -> None:
    store = StateStore()
    event_list = store.list_events(task_id)
    if not event_list:
        console.print(f"No events found for task `{task_id}`.")
        raise typer.Exit(code=1)
    console.print(render_events(event_list))


@app.command("reset-state")
def reset_state() -> None:
    store = StateStore()
    store.reset_state()
    console.print(Panel.fit("Q-IOS state store reset under .qios_state/.", title="State Reset"))


if __name__ == "__main__":
    app()
