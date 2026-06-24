from __future__ import annotations

from dataclasses import dataclass

from qios.control import (
    ArbitrationDecision,
    HealthScoreManager,
    PatchLocalArbitrator,
    PhiCache,
    RecoveryAction,
    RecoveryPolicyEngine,
    ReplayLedger,
    RollbackAnchorManager,
    SnapshotPackageBuilder,
    TelemetryCollector,
)
from qios.control.modulation_profile import ModulationProfileGenerator
from qios.models import PatchType, TaskRequest, TokenState
from qios.patch_runtime import PatchRuntime
from qios.policy_engine import PolicyEngine
from qios.recovery_engine import RecoveryEngine
from qios.routing import (
    DispatchPacketBuilder,
    PhysicalPatch,
    PhysicalPatchRegistry,
    Remapper,
    RouteCandidate,
    RouteEvaluator,
    VirtualPatchAddress,
    VirtualPatchAddressManager,
)
from qios.scheduler import Scheduler
from qios.sim.environment import PatchHealth, SimulationEnvironment
from qios.sim.metrics import SimulationMetrics
from qios.sim.workload import summarize_workload
from qios.structured_job import StructuredJobGenerator
from qios.token_engine import PhiTokenEngine


def _task_is_policy_invalid(task: TaskRequest) -> bool:
    constraints = task.constraints
    return (
        task.priority < 0
        or task.priority > 10
        or bool(constraints.get("force_invalid_patch_hint"))
        or "policy_invalid_reason" in constraints
    )


def _task_has_primary_failure(task: TaskRequest) -> bool:
    return bool(task.constraints.get("sim_primary_failure")) or "fail" in task.objective.lower()


@dataclass
class AttemptResult:
    success: bool
    latency_ms: float
    quarantined: bool
    congestion_failure: bool = False


class BaseSimulationSystem:
    system_name = "base"

    def __init__(self, environment: SimulationEnvironment) -> None:
        self.environment = environment.clone()
        self._baseline_patch_ids = self.environment.baseline_patch_ids()

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        raise NotImplementedError

    def _initialize_metrics(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)
        metrics.attach_workload_debug(**summarize_workload(tasks))
        return metrics

    def _policy_reject(self, metrics: SimulationMetrics) -> None:
        metrics.record_task(
            latency_ms=0.0,
            completed=False,
            policy_rejected=True,
        )

    def _baseline_patch_for_index(self, index: int) -> str:
        return self._baseline_patch_ids[index % len(self._baseline_patch_ids)]

    def _fixed_primary_patch(self) -> str:
        return self._baseline_patch_ids[0]

    def _attempt_on_patch(
        self,
        *,
        patch_id: str,
        runtime_success: bool,
        is_fallback: bool,
    ) -> AttemptResult:
        latency_ms, congestion_event = self.environment.prepare_attempt(patch_id)
        success = runtime_success
        congestion_failure = False

        if success and is_fallback and self.environment.sample_fallback_failure():
            success = False

        if success and self.environment.sample_patch_degradation_failure(patch_id):
            success = False

        if success and self.environment.sample_congestion_failure(patch_id, congestion_event):
            success = False
            congestion_failure = True

        quarantined = self.environment.register_patch_outcome(patch_id, success=success)
        return AttemptResult(
            success=success,
            latency_ms=latency_ms,
            quarantined=quarantined,
            congestion_failure=congestion_failure,
        )


class DirectExecutionBaseline(BaseSimulationSystem):
    system_name = "direct"

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = self._initialize_metrics(tasks)
        primary_patch_id = self._fixed_primary_patch()

        for task in tasks:
            if _task_is_policy_invalid(task):
                self._policy_reject(metrics)
                continue

            attempt = self._attempt_on_patch(
                patch_id=primary_patch_id,
                runtime_success=not _task_has_primary_failure(task),
                is_fallback=False,
            )
            metrics.record_execution_attempt(
                is_fallback=False,
                failed=not attempt.success,
                congestion_failure=attempt.congestion_failure,
            )
            metrics.record_task(
                latency_ms=attempt.latency_ms,
                completed=attempt.success,
                runtime_failed=not attempt.success,
                quarantines=1 if attempt.quarantined else 0,
            )

        return metrics


class RetryOnlyBaseline(BaseSimulationSystem):
    system_name = "retry_only"

    def __init__(self, environment: SimulationEnvironment, max_retries: int = 2) -> None:
        super().__init__(environment)
        self.max_retries = max_retries

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = self._initialize_metrics(tasks)
        primary_patch_id = self._fixed_primary_patch()

        for task in tasks:
            if _task_is_policy_invalid(task):
                self._policy_reject(metrics)
                continue

            latency_ms = 0.0
            restarts = 0
            quarantines = 0
            completed = False

            for attempt_index in range(self.max_retries + 1):
                attempt = self._attempt_on_patch(
                    patch_id=primary_patch_id,
                    runtime_success=not _task_has_primary_failure(task),
                    is_fallback=False,
                )
                metrics.record_execution_attempt(
                    is_fallback=False,
                    failed=not attempt.success,
                    congestion_failure=attempt.congestion_failure,
                )
                latency_ms += attempt.latency_ms
                quarantines += 1 if attempt.quarantined else 0
                if attempt.success:
                    completed = True
                    break
                if attempt_index < self.max_retries:
                    restarts += 1

            metrics.record_task(
                latency_ms=latency_ms,
                completed=completed,
                runtime_failed=not completed,
                full_restarts=restarts,
                quarantines=quarantines,
            )

        return metrics


class StaticRoutingBaseline(BaseSimulationSystem):
    system_name = "static"

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = self._initialize_metrics(tasks)

        for index, task in enumerate(tasks):
            if _task_is_policy_invalid(task):
                self._policy_reject(metrics)
                continue

            patch_id = self._baseline_patch_for_index(index)
            latency_ms = 0.0
            restarts = 0
            quarantines = 0

            first_attempt = self._attempt_on_patch(
                patch_id=patch_id,
                runtime_success=not _task_has_primary_failure(task),
                is_fallback=False,
            )
            metrics.record_execution_attempt(
                is_fallback=False,
                failed=not first_attempt.success,
                congestion_failure=first_attempt.congestion_failure,
            )
            latency_ms += first_attempt.latency_ms
            quarantines += 1 if first_attempt.quarantined else 0

            completed = first_attempt.success
            if not first_attempt.success:
                restarts = 1
                second_attempt = self._attempt_on_patch(
                    patch_id=patch_id,
                    runtime_success=not _task_has_primary_failure(task),
                    is_fallback=False,
                )
                metrics.record_execution_attempt(
                    is_fallback=False,
                    failed=not second_attempt.success,
                    congestion_failure=second_attempt.congestion_failure,
                )
                latency_ms += second_attempt.latency_ms
                quarantines += 1 if second_attempt.quarantined else 0
                completed = second_attempt.success

            metrics.record_task(
                latency_ms=latency_ms,
                completed=completed,
                runtime_failed=not completed,
                full_restarts=restarts,
                quarantines=quarantines,
            )

        return metrics


class QIOSSimulationSystem(BaseSimulationSystem):
    system_name = "qios"

    def __init__(self, environment: SimulationEnvironment, max_reroutes: int = 1) -> None:
        super().__init__(environment)
        self.max_reroutes = max_reroutes
        self.generator = StructuredJobGenerator()
        self.token_engine = PhiTokenEngine()
        self.policy_engine = PolicyEngine()
        self.scheduler = Scheduler()
        self.recovery_engine = RecoveryEngine()
        self.runtime = PatchRuntime()
        self.phi_cache = PhiCache()
        self.modulation_generator = ModulationProfileGenerator()
        self.arbitrator = PatchLocalArbitrator()
        self.snapshot_builder = SnapshotPackageBuilder()
        self.replay_ledger = ReplayLedger()
        self.rollback_manager = RollbackAnchorManager()
        self.health_manager = HealthScoreManager()
        self.telemetry = TelemetryCollector()
        self.recovery_policy = RecoveryPolicyEngine()
        self.virtual_patch_manager = VirtualPatchAddressManager()
        self.patch_registry = PhysicalPatchRegistry()
        self.route_evaluator = RouteEvaluator()
        self.dispatch_builder = DispatchPacketBuilder()
        self.remapper = Remapper(self.virtual_patch_manager)
        self._register_environment_patches()

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = self._initialize_metrics(tasks)

        for task in tasks:
            control_metrics = self._empty_control_metrics()
            task_copy = task.model_copy(deep=True)
            structured_job = self.generator.generate(task_copy)
            token = self.token_engine.create_token(structured_job)
            self._sync_patch_registry()
            self._append_replay_event(
                control_metrics,
                token,
                event_type="token_created",
                patch_id=token.patch_hint,
                message="Simulation token created.",
            )
            planned_patch_id = token.patch_hint or PatchType.ANALYSIS.value
            planned_anchor = self._create_anchor(
                control_metrics,
                token,
                patch_id=planned_patch_id,
                anchor_type="planned",
                metadata={"objective": task_copy.objective},
            )
            self._capture_snapshot(
                control_metrics,
                token,
                patch_id=planned_patch_id,
                rollback_anchor_id=planned_anchor.anchor_id,
                phase="planned",
            )

            if task_copy.constraints.get("force_invalid_patch_hint"):
                token.patch_hint = PatchType.ANALYSIS.value
                token.metadata["constraints"] = task_copy.constraints

            admissible, _ = self.policy_engine.check_admissibility(token)
            if not admissible:
                self._append_replay_event(
                    control_metrics,
                    token,
                    event_type="admissibility_rejected",
                    patch_id=token.patch_hint,
                    message="Policy rejected the token.",
                )
                rejection_anchor = self._create_anchor(
                    control_metrics,
                    token,
                    patch_id=token.patch_hint or PatchType.ANALYSIS.value,
                    anchor_type="policy_rejected",
                )
                self._capture_snapshot(
                    control_metrics,
                    token,
                    patch_id=token.patch_hint or PatchType.ANALYSIS.value,
                    rollback_anchor_id=rejection_anchor.anchor_id,
                    phase="policy_rejected",
                )
                metrics.record_control_plane(control_metrics)
                self._policy_reject(metrics)
                continue
            self._append_replay_event(
                control_metrics,
                token,
                event_type="admissibility_passed",
                patch_id=token.patch_hint,
                message="Policy admitted the token.",
            )

            self.scheduler.assign_patch(token)
            primary_patch = self._select_primary_patch(token)
            if primary_patch is None:
                metrics.record_control_plane(control_metrics)
                metrics.record_task(
                    latency_ms=0.0,
                    completed=False,
                    runtime_failed=True,
                    failed_recovery=True,
                )
                continue

            primary_alternative = self._select_recovery_patch(task_copy, token, {primary_patch.patch_id})
            primary_patch, primary_arbitration = self._select_patch_with_control(
                token=token,
                preferred_patch=primary_patch,
                alternative_patch=primary_alternative,
                control_metrics=control_metrics,
            )
            token.patch_hint = primary_patch.patch_type
            token.assigned_patch = primary_patch.patch_type

            candidate_patches = self._candidate_physical_patches(
                task_copy,
                token,
                exclude_patch_ids=set(),
            )
            if not candidate_patches:
                metrics.record_control_plane(control_metrics)
                metrics.record_task(
                    latency_ms=0.0,
                    completed=False,
                    runtime_failed=True,
                    failed_recovery=True,
                )
                continue

            virtual_patch = self._create_virtual_patch(
                token,
                task_copy,
                [patch.patch_id for patch in candidate_patches],
                control_metrics,
            )
            route_candidates = self._evaluate_routes(
                token,
                virtual_patch,
                candidate_patches,
                control_metrics,
            )
            selected_route = self._choose_route_candidate(
                route_candidates,
                preferred_patch_id=primary_patch.patch_id,
            )
            if selected_route is None:
                metrics.record_control_plane(control_metrics)
                metrics.record_task(
                    latency_ms=0.0,
                    completed=False,
                    runtime_failed=True,
                    failed_recovery=True,
                )
                continue

            selected_physical_patch = self.patch_registry.get_patch(selected_route.physical_patch_id)
            if selected_physical_patch is None:
                metrics.record_control_plane(control_metrics)
                metrics.record_task(
                    latency_ms=0.0,
                    completed=False,
                    runtime_failed=True,
                    failed_recovery=True,
                )
                continue

            dispatch_packet = self._create_dispatch_packet(
                token,
                virtual_patch,
                selected_route,
                task_copy.fallback,
                control_metrics,
            )

            assigned_anchor = self._create_anchor(
                control_metrics,
                token,
                patch_id=selected_physical_patch.patch_id,
                anchor_type="assigned",
                metadata={"decision": primary_arbitration.decision.value},
            )
            self._capture_snapshot(
                control_metrics,
                token,
                patch_id=selected_physical_patch.patch_id,
                rollback_anchor_id=assigned_anchor.anchor_id,
                phase="assigned",
                virtual_patch_id=virtual_patch.virtual_patch_id,
                physical_patch_id=selected_physical_patch.patch_id,
                route_id=selected_route.route_id,
                dispatch_id=dispatch_packet.dispatch_id,
                metadata={
                    "arbitration": primary_arbitration.model_dump(mode="json"),
                    "dispatch_id": dispatch_packet.dispatch_id,
                },
            )
            self._append_replay_event(
                control_metrics,
                token,
                event_type="patch_assigned",
                patch_id=selected_physical_patch.patch_id,
                virtual_patch_id=virtual_patch.virtual_patch_id,
                route_id=selected_route.route_id,
                dispatch_id=dispatch_packet.dispatch_id,
                message=f"Assigned to {selected_physical_patch.patch_id}.",
            )

            primary_failure_patch_id = (
                selected_physical_patch.patch_id if _task_has_primary_failure(task_copy) else None
            )
            total_latency_ms = 0.0
            reroutes = 0
            fallback_dispatches = 0
            quarantines = 0
            tried_patch_ids = {selected_physical_patch.patch_id}

            primary_attempt = self._execute_attempt(
                task=task_copy,
                token=token,
                physical_patch=selected_physical_patch,
                virtual_patch=virtual_patch,
                route_candidate=selected_route,
                dispatch_packet=dispatch_packet,
                primary_failure_patch_id=primary_failure_patch_id,
                control_metrics=control_metrics,
                phase="primary_execution",
            )
            metrics.record_execution_attempt(
                is_fallback=False,
                failed=not primary_attempt.success,
                congestion_failure=primary_attempt.congestion_failure,
            )
            total_latency_ms += primary_attempt.latency_ms
            quarantines += 1 if primary_attempt.quarantined else 0

            if primary_attempt.success:
                metrics.record_control_plane(control_metrics)
                metrics.record_task(
                    latency_ms=total_latency_ms,
                    completed=True,
                    quarantines=quarantines,
                )
                continue

            recovered = False
            failed_recovery = True
            max_reroute_exhausted = False
            failed_physical_patch_id = selected_physical_patch.patch_id
            failed_route_id = selected_route.route_id

            while reroutes < self.max_reroutes:
                reroutes += 1
                self._increment_control(control_metrics, "local_reentry_count")
                self.phi_cache.update_reroute(failed_physical_patch_id, token.role)
                self._increment_control(control_metrics, "phi_cache_updates")

                candidate_patches = self._candidate_physical_patches(
                    task_copy,
                    token,
                    exclude_patch_ids=tried_patch_ids,
                    include_quarantined=True,
                )
                candidate_patch_ids = [patch.patch_id for patch in candidate_patches]
                recovery_decision = self.recovery_policy.decide(
                    token=token,
                    failed_patch_id=failed_physical_patch_id,
                    failed_route_id=failed_route_id,
                    failed_patches=set(tried_patch_ids),
                    candidate_patch_ids=candidate_patch_ids,
                    health_manager=self.health_manager,
                    route_evaluator=self.route_evaluator,
                    max_reroutes=self.max_reroutes,
                    current_reroutes=reroutes - 1,
                    fallback_patch_id=self._fallback_physical_patch_id(task_copy),
                )
                self._record_recovery_policy(control_metrics, recovery_decision)
                self._append_replay_event(
                    control_metrics,
                    token,
                    event_type="recovery_policy_decided",
                    patch_id=failed_physical_patch_id,
                    virtual_patch_id=virtual_patch.virtual_patch_id,
                    route_id=failed_route_id,
                    message=recovery_decision.reason,
                    metadata=recovery_decision.model_dump(mode="json"),
                )

                if recovery_decision.should_quarantine_failed_patch:
                    self.health_manager.quarantine(failed_physical_patch_id)
                    self.patch_registry.mark_quarantined(failed_physical_patch_id)
                    self._increment_control(control_metrics, "health_score_updates")
                    self._record_health_metric(
                        control_metrics,
                        self.health_manager.get_score(failed_physical_patch_id).health_score,
                    )
                    quarantines += 1
                self._update_quarantine_metric(control_metrics)

                if recovery_decision.action == RecoveryAction.FAIL:
                    break

                target_patch_id = recovery_decision.target_patch_id
                remap_route_id = recovery_decision.target_route_id
                if recovery_decision.action in {
                    RecoveryAction.REROUTE,
                    RecoveryAction.LOCAL_REENTRY,
                    RecoveryAction.SNAPSHOT_RESTORE,
                }:
                    self._increment_control(control_metrics, "remap_attempts")
                    remap_result = self.remapper.remap(
                        virtual_patch_id=virtual_patch.virtual_patch_id,
                        failed_physical_patch_id=failed_physical_patch_id,
                        candidate_patch_ids=candidate_patch_ids,
                        health_manager=self.health_manager,
                        route_evaluator=self.route_evaluator,
                        patch_registry=self.patch_registry,
                    )
                    if remap_result.success:
                        self._increment_control(control_metrics, "remap_successes")
                        target_patch_id = remap_result.new_physical_patch_id
                        remap_route_id = remap_result.route_id
                    else:
                        self._increment_control(control_metrics, "remap_failures")
                        self._append_replay_event(
                            control_metrics,
                            token,
                            event_type="remap_failed",
                            patch_id=failed_physical_patch_id,
                            virtual_patch_id=virtual_patch.virtual_patch_id,
                            route_id=failed_route_id,
                            message=remap_result.reason,
                            metadata=remap_result.model_dump(mode="json"),
                        )
                        break
                    self._append_replay_event(
                        control_metrics,
                        token,
                        event_type="remap_completed",
                        patch_id=target_patch_id,
                        virtual_patch_id=virtual_patch.virtual_patch_id,
                        route_id=remap_route_id,
                        message=remap_result.reason,
                        metadata=remap_result.model_dump(mode="json"),
                    )
                elif recovery_decision.action == RecoveryAction.FALLBACK_DISPATCH:
                    if target_patch_id is None:
                        break
                    self._increment_control(control_metrics, "remap_attempts")
                    self._increment_control(control_metrics, "remap_successes")
                    self.virtual_patch_manager.preserve_virtual_address_on_remap(
                        virtual_patch.virtual_patch_id,
                        target_patch_id,
                    )
                    fallback_dispatches += 1
                    self._append_replay_event(
                        control_metrics,
                        token,
                        event_type="fallback_dispatch_selected",
                        patch_id=target_patch_id,
                        virtual_patch_id=virtual_patch.virtual_patch_id,
                        route_id=remap_route_id,
                        message=recovery_decision.reason,
                    )

                if target_patch_id is None:
                    break

                recovery_patch = self.patch_registry.get_patch(target_patch_id)
                if recovery_patch is None:
                    break

                recovery_routes = self._evaluate_routes(
                    token,
                    virtual_patch,
                    [recovery_patch],
                    control_metrics,
                )
                recovery_route = self._choose_route_candidate(
                    recovery_routes,
                    preferred_patch_id=target_patch_id,
                )
                if recovery_route is None:
                    break

                recovery_dispatch = self._create_dispatch_packet(
                    token,
                    virtual_patch,
                    recovery_route,
                    task_copy.fallback,
                    control_metrics,
                )
                self._append_replay_event(
                    control_metrics,
                    token,
                    event_type="recovery_started",
                    patch_id=recovery_patch.patch_id,
                    virtual_patch_id=virtual_patch.virtual_patch_id,
                    route_id=recovery_route.route_id,
                    dispatch_id=recovery_dispatch.dispatch_id,
                    message=recovery_decision.reason,
                )
                recovery_anchor = self._create_anchor(
                    control_metrics,
                    token,
                    patch_id=recovery_patch.patch_id,
                    anchor_type="recovery_assignment",
                    metadata={"decision": recovery_decision.action.value},
                )
                self.recovery_engine.recover(
                    token,
                    recovery_decision.reason,
                    rollback_anchor_id=recovery_anchor.anchor_id,
                    replay_lineage=self.replay_ledger.get_replay_lineage(token.token_id),
                    failed_patches=sorted(tried_patch_ids),
                    alternative_patch=recovery_patch.patch_type,
                )
                self._capture_snapshot(
                    control_metrics,
                    token,
                    patch_id=recovery_patch.patch_id,
                    rollback_anchor_id=recovery_anchor.anchor_id,
                    phase="recovery_assignment",
                    virtual_patch_id=virtual_patch.virtual_patch_id,
                    physical_patch_id=recovery_patch.patch_id,
                    route_id=recovery_route.route_id,
                    dispatch_id=recovery_dispatch.dispatch_id,
                    metadata={"decision": recovery_decision.model_dump(mode="json")},
                )

                tried_patch_ids.add(recovery_patch.patch_id)
                reroute_attempt = self._execute_attempt(
                    task=task_copy,
                    token=token,
                    physical_patch=recovery_patch,
                    virtual_patch=virtual_patch,
                    route_candidate=recovery_route,
                    dispatch_packet=recovery_dispatch,
                    primary_failure_patch_id=primary_failure_patch_id,
                    control_metrics=control_metrics,
                    phase="recovery_execution",
                )
                metrics.record_execution_attempt(
                    is_fallback=(
                        recovery_patch.patch_type == PatchType.FALLBACK.value
                        and task_copy.fallback is not None
                    ),
                    failed=not reroute_attempt.success,
                    congestion_failure=reroute_attempt.congestion_failure,
                )
                total_latency_ms += reroute_attempt.latency_ms
                quarantines += 1 if reroute_attempt.quarantined else 0

                if reroute_attempt.success:
                    recovered = True
                    failed_recovery = False
                    break
                failed_physical_patch_id = recovery_patch.patch_id
                failed_route_id = recovery_route.route_id

            if not recovered and reroutes >= self.max_reroutes and self.max_reroutes > 0:
                max_reroute_exhausted = True

            self._update_quarantine_metric(control_metrics)
            metrics.record_control_plane(control_metrics)
            metrics.record_task(
                latency_ms=total_latency_ms,
                completed=recovered,
                recovered=recovered,
                runtime_failed=not recovered,
                failed_recovery=failed_recovery,
                reroutes=reroutes,
                fallback_dispatches=fallback_dispatches,
                quarantines=quarantines,
                max_reroute_exhausted=max_reroute_exhausted,
            )

        return metrics

    def _empty_control_metrics(self) -> dict[str, int]:
        return {
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
            "health_score_updates": 0,
            "telemetry_events": 0,
            "recovery_policy_decisions": 0,
            "recovery_policy_reroutes": 0,
            "recovery_policy_fallbacks": 0,
            "recovery_policy_failures": 0,
            "virtual_patches_created": 0,
            "routes_evaluated": 0,
            "dispatch_packets_created": 0,
            "remap_attempts": 0,
            "remap_successes": 0,
            "remap_failures": 0,
            "route_score_total": 0.0,
            "route_score_count": 0,
            "health_score_total": 0.0,
            "health_score_count": 0,
            "quarantined_patch_count": 0,
        }

    def _increment_control(self, control_metrics: dict[str, int], key: str, amount: int = 1) -> None:
        control_metrics[key] = control_metrics.get(key, 0) + amount

    def _record_route_metrics(
        self,
        control_metrics: dict[str, int | float],
        route_candidates: list[RouteCandidate],
    ) -> None:
        self._increment_control(control_metrics, "routes_evaluated", len(route_candidates))
        control_metrics["route_score_total"] = control_metrics.get("route_score_total", 0.0) + sum(
            route.final_score for route in route_candidates
        )
        control_metrics["route_score_count"] = control_metrics.get("route_score_count", 0) + len(route_candidates)

    def _record_health_metric(self, control_metrics: dict[str, int | float], health_score: float) -> None:
        control_metrics["health_score_total"] = control_metrics.get("health_score_total", 0.0) + health_score
        control_metrics["health_score_count"] = control_metrics.get("health_score_count", 0) + 1

    def _update_quarantine_metric(self, control_metrics: dict[str, int | float]) -> None:
        control_metrics["quarantined_patch_count"] = sum(
            1 for patch in self.patch_registry.list_patches() if patch.quarantined
        )

    def _record_recovery_policy(self, control_metrics: dict[str, int], decision) -> None:
        self._increment_control(control_metrics, "recovery_policy_decisions")
        if decision.action == RecoveryAction.REROUTE:
            self._increment_control(control_metrics, "recovery_policy_reroutes")
        elif decision.action == RecoveryAction.FALLBACK_DISPATCH:
            self._increment_control(control_metrics, "recovery_policy_fallbacks")
        elif decision.action == RecoveryAction.FAIL:
            self._increment_control(control_metrics, "recovery_policy_failures")

    def _append_replay_event(
        self,
        control_metrics: dict[str, int],
        token,
        *,
        event_type: str,
        patch_id: str | None = None,
        virtual_patch_id: str | None = None,
        route_id: str | None = None,
        dispatch_id: str | None = None,
        message: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.replay_ledger.append_event(
            task_id=token.task_id,
            token_id=token.token_id,
            event_type=event_type,
            patch_id=patch_id,
            virtual_patch_id=virtual_patch_id,
            route_id=route_id,
            dispatch_id=dispatch_id,
            token_state=token.lifecycle_state.value,
            message=message,
            metadata=metadata,
        )
        self._increment_control(control_metrics, "replay_ledger_events")

    def _create_anchor(
        self,
        control_metrics: dict[str, int],
        token,
        *,
        patch_id: str,
        anchor_type: str,
        metadata: dict[str, object] | None = None,
    ):
        anchor = self.rollback_manager.create_anchor(
            task_id=token.task_id,
            token_id=token.token_id,
            patch_id=patch_id,
            anchor_type=anchor_type,
            token_state=token.lifecycle_state.value,
            replay_position=len(self.rollback_manager.list_anchors(token.token_id)),
            metadata=metadata,
        )
        self._increment_control(control_metrics, "rollback_anchors_created")
        return anchor

    def _capture_snapshot(
        self,
        control_metrics: dict[str, int],
        token,
        *,
        patch_id: str,
        rollback_anchor_id: str,
        phase: str,
        virtual_patch_id: str | None = None,
        physical_patch_id: str | None = None,
        route_id: str | None = None,
        dispatch_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.snapshot_builder.build(
            token=token,
            patch_id=patch_id,
            rollback_anchor_id=rollback_anchor_id,
            replay_lineage=self.replay_ledger.get_replay_lineage(token.token_id),
            memory_isolation_label=patch_id,
            virtual_patch_id=virtual_patch_id,
            physical_patch_id=physical_patch_id or patch_id,
            route_id=route_id,
            dispatch_id=dispatch_id,
            metadata={"phase": phase, **(metadata or {})},
        )
        self._increment_control(control_metrics, "snapshots_created")

    def _register_environment_patches(self) -> None:
        for patch in self.environment.patches.values():
            self.patch_registry.register_patch(
                PhysicalPatch(
                    patch_id=patch.patch_id,
                    patch_type=patch.patch_type,
                    domain=patch.patch_type,
                    supported_roles=self._supported_roles_for_patch_type(patch.patch_type),
                    isolation_domain="default",
                    capacity=8,
                    current_load=0,
                    health_score=patch.health_score,
                    congestion_score=patch.congestion_score,
                    quarantined=patch.quarantined,
                )
            )

    def _sync_patch_registry(self) -> None:
        for patch in self.environment.patches.values():
            registry_patch = self.patch_registry.get_patch(patch.patch_id)
            if registry_patch is None:
                self.patch_registry.register_patch(
                    PhysicalPatch(
                        patch_id=patch.patch_id,
                        patch_type=patch.patch_type,
                        domain=patch.patch_type,
                        supported_roles=self._supported_roles_for_patch_type(patch.patch_type),
                        isolation_domain="default",
                        capacity=8,
                        current_load=0,
                        health_score=patch.health_score,
                        congestion_score=patch.congestion_score,
                        quarantined=patch.quarantined,
                    )
                )
                continue
            registry_patch.health_score = patch.health_score
            registry_patch.congestion_score = patch.congestion_score
            registry_patch.quarantined = patch.quarantined or self.health_manager.is_quarantined(patch.patch_id)

    def _supported_roles_for_patch_type(self, patch_type: str) -> list[str]:
        return ["analysis", "execution", "default_execution"]

    def _candidate_physical_patches(
        self,
        task: TaskRequest,
        token,
        *,
        exclude_patch_ids: set[str],
        include_quarantined: bool = False,
    ) -> list[PhysicalPatch]:
        self._sync_patch_registry()
        candidates = self.patch_registry.list_candidate_patches(
            role=token.role,
            exclude_quarantined=not include_quarantined,
        )
        if not candidates and not include_quarantined:
            candidates = self.patch_registry.list_candidate_patches(
                role=token.role,
                exclude_quarantined=False,
            )
        if task.fallback is None:
            candidates = [patch for patch in candidates if patch.patch_type != PatchType.FALLBACK.value]
        candidates = [patch for patch in candidates if patch.patch_id not in exclude_patch_ids]
        preferred_type = token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value
        return sorted(
            candidates,
            key=lambda patch: (
                patch.patch_type == preferred_type,
                not patch.quarantined,
                patch.health_score,
                -patch.congestion_score,
                patch.patch_id,
            ),
            reverse=True,
        )

    def _fallback_physical_patch_id(self, task: TaskRequest) -> str | None:
        if task.fallback is None:
            return None
        for patch in self.patch_registry.list_patches():
            if patch.patch_type == task.fallback:
                return patch.patch_id
        return None

    def _create_virtual_patch(
        self,
        token,
        task: TaskRequest,
        candidate_patch_ids: list[str],
        control_metrics: dict[str, int],
    ) -> VirtualPatchAddress:
        virtual_patch = self.virtual_patch_manager.create_virtual_patch(
            logic_id=token.token_id,
            role=token.role,
            preferred_patch_type=token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value,
            allowed_physical_patch_ids=candidate_patch_ids,
            isolation_domain="default",
            metadata={"task_id": task.task_id},
        )
        self._increment_control(control_metrics, "virtual_patches_created")
        self._append_replay_event(
            control_metrics,
            token,
            event_type="virtual_patch_created",
            patch_id=token.assigned_patch or token.patch_hint,
            virtual_patch_id=virtual_patch.virtual_patch_id,
            message="Virtual patch address created for token.",
            metadata={"allowed_physical_patch_ids": candidate_patch_ids},
        )
        return virtual_patch

    def _evaluate_routes(
        self,
        token,
        virtual_patch: VirtualPatchAddress,
        candidate_patches: list[PhysicalPatch],
        control_metrics: dict[str, int | float],
    ) -> list[RouteCandidate]:
        routes = self.route_evaluator.evaluate_routes(
            virtual_patch=virtual_patch,
            candidate_patches=candidate_patches,
            health_manager=self.health_manager,
            patch_registry=self.patch_registry,
            phi_cache=self.phi_cache,
            congestion_map={patch.patch_id: patch.congestion_score for patch in candidate_patches},
        )
        self._record_route_metrics(control_metrics, routes)
        if routes:
            self._append_replay_event(
                control_metrics,
                token,
                event_type="routes_evaluated",
                patch_id=routes[0].physical_patch_id,
                virtual_patch_id=virtual_patch.virtual_patch_id,
                route_id=routes[0].route_id,
                message="Candidate routes evaluated for virtual patch.",
                metadata={"route_count": len(routes)},
            )
        return routes

    def _choose_route_candidate(
        self,
        route_candidates: list[RouteCandidate],
        *,
        preferred_patch_id: str | None = None,
    ) -> RouteCandidate | None:
        if not route_candidates:
            return None
        if preferred_patch_id is None:
            return route_candidates[0]
        preferred = next(
            (route for route in route_candidates if route.physical_patch_id == preferred_patch_id),
            None,
        )
        if preferred is not None and preferred.final_score >= route_candidates[0].final_score - 0.08:
            return preferred
        return route_candidates[0]

    def _create_dispatch_packet(
        self,
        token,
        virtual_patch: VirtualPatchAddress,
        route_candidate: RouteCandidate,
        fallback_patch_id: str | None,
        control_metrics: dict[str, int],
    ):
        dispatch_packet = self.dispatch_builder.build(
            token=token,
            virtual_patch=virtual_patch,
            route_candidate=route_candidate,
            fallback_patch_id=fallback_patch_id,
            metadata={"survivability_score": route_candidate.survivability_score},
        )
        self._increment_control(control_metrics, "dispatch_packets_created")
        self._append_replay_event(
            control_metrics,
            token,
            event_type="dispatch_packet_created",
            patch_id=route_candidate.physical_patch_id,
            virtual_patch_id=virtual_patch.virtual_patch_id,
            route_id=route_candidate.route_id,
            dispatch_id=dispatch_packet.dispatch_id,
            message="Dispatch packet created for route handoff.",
        )
        return dispatch_packet

    def _select_patch_with_control(
        self,
        *,
        token,
        preferred_patch: PatchHealth,
        alternative_patch: PatchHealth | None,
        control_metrics: dict[str, int],
    ) -> tuple[PatchHealth, object]:
        candidates = [preferred_patch]
        if alternative_patch is not None and alternative_patch.patch_id != preferred_patch.patch_id:
            candidates.append(alternative_patch)

        candidate_ids = [patch.patch_id for patch in candidates]
        if any(self.phi_cache.get_entry(patch_id, token.role).has_history for patch_id in candidate_ids):
            self._increment_control(control_metrics, "phi_cache_hits")

        profile = self.modulation_generator.generate(
            token,
            candidate_patch_ids=candidate_ids,
            phi_cache=self.phi_cache,
            patch_health={patch.patch_id: patch.health_score for patch in candidates},
            patch_congestion={patch.patch_id: patch.congestion_score for patch in candidates},
        )
        self._increment_control(control_metrics, "modulation_profiles_created")
        self._append_replay_event(
            control_metrics,
            token,
            event_type="modulation_profile_generated",
            patch_id=profile.selected_patch_id,
            message="Generated modulation profile for candidate patches.",
            metadata={"scores": [score.model_dump(mode="json") for score in profile.patch_scores]},
        )
        arbitration = self.arbitrator.arbitrate(
            token,
            profile,
            patch_health={patch.patch_id: patch.health_score for patch in candidates},
            patch_congestion={patch.patch_id: patch.congestion_score for patch in candidates},
            quarantined_patches={patch.patch_id for patch in candidates if patch.quarantined},
        )
        if arbitration.decision == ArbitrationDecision.ACCEPT:
            self._increment_control(control_metrics, "arbitration_accepts")
        elif arbitration.decision == ArbitrationDecision.REJECT:
            self._increment_control(control_metrics, "arbitration_rejects")
        elif arbitration.decision == ArbitrationDecision.DEFER:
            self._increment_control(control_metrics, "arbitration_defers")
        else:
            self._increment_control(control_metrics, "arbitration_reroutes")

        selected_patch_id = profile.selected_patch_id or preferred_patch.patch_id
        if arbitration.decision != ArbitrationDecision.ACCEPT and arbitration.alternative_patch_id is not None:
            selected_patch_id = arbitration.alternative_patch_id

        selected_patch = next(
            (patch for patch in candidates if patch.patch_id == selected_patch_id),
            preferred_patch,
        )
        if (
            arbitration.decision != ArbitrationDecision.ACCEPT
            and selected_patch.patch_id != preferred_patch.patch_id
        ):
            self._append_replay_event(
                control_metrics,
                token,
                event_type="arbitration_rerouted",
                patch_id=selected_patch.patch_id,
                message=f"Arbitration rerouted from {preferred_patch.patch_id} to {selected_patch.patch_id}.",
            )
        return selected_patch, arbitration

    def _select_primary_patch(self, token) -> PatchHealth | None:
        preferred_types = [token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value]
        patch = self.environment.select_best_patch(
            preferred_types=preferred_types,
            include_quarantined=False,
        )
        if patch is not None:
            return patch
        return self.environment.select_best_patch(
            preferred_types=preferred_types,
            include_quarantined=True,
        )

    def _select_recovery_patch(
        self,
        task: TaskRequest,
        token,
        tried_patch_ids: set[str],
    ) -> PatchHealth | None:
        candidate_types: list[list[str] | None] = []

        if task.fallback:
            candidate_types.append([PatchType.FALLBACK.value])

        if task.constraints.get("sandbox_required"):
            candidate_types.append([PatchType.SANDBOX.value])
        elif token.role == "analysis":
            candidate_types.append([PatchType.ANALYSIS.value])
        else:
            candidate_types.append([PatchType.SANDBOX.value, PatchType.ANALYSIS.value])

        candidate_types.append([PatchType.HUMAN_REVIEW.value, PatchType.ANALYSIS.value, PatchType.SANDBOX.value])
        candidate_types.append(None)

        for preferred_types in candidate_types:
            patch = self.environment.select_best_patch(
                preferred_types=preferred_types,
                exclude_ids=tried_patch_ids,
                include_quarantined=False,
                allow_fallback=bool(task.fallback),
            )
            if patch is not None:
                return patch

        for preferred_types in candidate_types:
            patch = self.environment.select_best_patch(
                preferred_types=preferred_types,
                exclude_ids=None,
                include_quarantined=True,
                allow_fallback=bool(task.fallback),
            )
            if patch is not None:
                return patch

        return None

    def _execute_attempt(
        self,
        *,
        task: TaskRequest,
        token,
        physical_patch: PhysicalPatch,
        virtual_patch: VirtualPatchAddress,
        route_candidate: RouteCandidate,
        dispatch_packet,
        primary_failure_patch_id: str | None,
        control_metrics: dict[str, int],
        phase: str,
    ) -> AttemptResult:
        token.assigned_patch = physical_patch.patch_type
        token.patch_hint = physical_patch.patch_type
        token.metadata["current_patch_id"] = physical_patch.patch_id
        token.metadata["virtual_patch_id"] = virtual_patch.virtual_patch_id
        token.metadata["route_id"] = route_candidate.route_id
        token.metadata["dispatch_id"] = dispatch_packet.dispatch_id
        token.metadata["sim_force_failure"] = (
            primary_failure_patch_id is not None
            and physical_patch.patch_id == primary_failure_patch_id
            and physical_patch.patch_type != PatchType.FALLBACK.value
        )
        execution_anchor = self._create_anchor(
            control_metrics,
            token,
            patch_id=physical_patch.patch_id,
            anchor_type=phase,
        )
        token.metadata["rollback_anchor_id"] = execution_anchor.anchor_id
        self._capture_snapshot(
            control_metrics,
            token,
            patch_id=physical_patch.patch_id,
            rollback_anchor_id=execution_anchor.anchor_id,
            phase=phase,
            virtual_patch_id=virtual_patch.virtual_patch_id,
            physical_patch_id=physical_patch.patch_id,
            route_id=route_candidate.route_id,
            dispatch_id=dispatch_packet.dispatch_id,
        )
        self._append_replay_event(
            control_metrics,
            token,
            event_type=f"{phase}_started",
            patch_id=physical_patch.patch_id,
            virtual_patch_id=virtual_patch.virtual_patch_id,
            route_id=route_candidate.route_id,
            dispatch_id=dispatch_packet.dispatch_id,
            message=f"Execution attempt started on {physical_patch.patch_id}.",
        )
        self.patch_registry.update_load(physical_patch.patch_id, 1)
        runtime_result = self.runtime.execute(token)
        token.metadata["sim_force_failure"] = False

        attempt = self._attempt_on_patch(
            patch_id=physical_patch.patch_id,
            runtime_success=runtime_result.success,
            is_fallback=physical_patch.patch_type == PatchType.FALLBACK.value and task.fallback is not None,
        )
        self.patch_registry.update_load(physical_patch.patch_id, -1)
        self._sync_patch_registry()
        environment_patch = self.environment.patches[physical_patch.patch_id]
        health_score = self.health_manager.record_congestion(
            physical_patch.patch_id,
            environment_patch.congestion_score,
        )
        self._increment_control(control_metrics, "health_score_updates")

        if not attempt.success:
            token.lifecycle_state = TokenState.FAILED
            token.metadata["last_failed_patch_id"] = physical_patch.patch_id
            health_score = self.health_manager.record_failure(
                physical_patch.patch_id,
                latency_ms=attempt.latency_ms,
                reason="Execution attempt failed.",
            )
            self._increment_control(control_metrics, "health_score_updates")
            self.telemetry.record_failure(
                task_id=token.task_id,
                token_id=token.token_id,
                patch_id=physical_patch.patch_id,
                route_id=route_candidate.route_id,
                latency_ms=attempt.latency_ms,
                failure_reason="Execution attempt failed.",
                congestion_score=environment_patch.congestion_score,
                health_score=health_score.health_score,
                metadata={"dispatch_id": dispatch_packet.dispatch_id, "phase": phase},
            )
            self._increment_control(control_metrics, "telemetry_events")
            self._record_health_metric(control_metrics, health_score.health_score)
            self.patch_registry.update_health(physical_patch.patch_id, health_score.health_score)
            self.patch_registry.update_congestion(physical_patch.patch_id, environment_patch.congestion_score)
            self.phi_cache.update_failure(
                physical_patch.patch_id,
                token.role,
                latency_ms=attempt.latency_ms,
                health_score=health_score.health_score,
            )
            self._append_replay_event(
                control_metrics,
                token,
                event_type=f"{phase}_failed",
                patch_id=physical_patch.patch_id,
                virtual_patch_id=virtual_patch.virtual_patch_id,
                route_id=route_candidate.route_id,
                dispatch_id=dispatch_packet.dispatch_id,
                message="Execution attempt failed.",
            )
        else:
            health_score = self.health_manager.record_success(
                physical_patch.patch_id,
                latency_ms=attempt.latency_ms,
            )
            self._increment_control(control_metrics, "health_score_updates")
            self.telemetry.record_success(
                task_id=token.task_id,
                token_id=token.token_id,
                patch_id=physical_patch.patch_id,
                route_id=route_candidate.route_id,
                latency_ms=attempt.latency_ms,
                congestion_score=environment_patch.congestion_score,
                health_score=health_score.health_score,
                metadata={"dispatch_id": dispatch_packet.dispatch_id, "phase": phase},
            )
            self._increment_control(control_metrics, "telemetry_events")
            self._record_health_metric(control_metrics, health_score.health_score)
            self.patch_registry.update_health(physical_patch.patch_id, health_score.health_score)
            self.patch_registry.update_congestion(physical_patch.patch_id, environment_patch.congestion_score)
            self.phi_cache.update_success(
                physical_patch.patch_id,
                token.role,
                latency_ms=attempt.latency_ms,
                health_score=health_score.health_score,
            )
            self._append_replay_event(
                control_metrics,
                token,
                event_type=f"{phase}_completed",
                patch_id=physical_patch.patch_id,
                virtual_patch_id=virtual_patch.virtual_patch_id,
                route_id=route_candidate.route_id,
                dispatch_id=dispatch_packet.dispatch_id,
                message="Execution attempt completed.",
            )
        self._increment_control(control_metrics, "phi_cache_updates")
        self._update_quarantine_metric(control_metrics)
        return attempt
