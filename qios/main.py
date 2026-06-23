from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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


def build_snapshot(task_request: TaskRequest, token) -> SnapshotPackage:
    return SnapshotPackage(
        task_id=task_request.task_id,
        token_id=token.token_id,
        lifecycle_state=token.lifecycle_state,
        assigned_patch=token.assigned_patch or token.patch_hint,
        phi_modulation=token.phi_modulation,
        payload={
            "task": task_request.model_dump(mode="json"),
            "token": token.model_dump(mode="json"),
        },
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


def submit_task_request(task_request: TaskRequest, state_store: StateStore | None = None) -> PipelineOutcome:
    store = state_store or StateStore()
    generator = StructuredJobGenerator()
    token_engine = PhiTokenEngine()
    policy_engine = PolicyEngine()
    scheduler = Scheduler()
    runtime = PatchRuntime()
    recovery_engine = RecoveryEngine()

    job = generator.generate(task_request)
    token = token_engine.create_token(job)

    store.save_task(task_request)
    store.save_token(token)
    store.save_snapshot(build_snapshot(task_request, token))
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
        store.save_snapshot(build_snapshot(task_request, token))
        return PipelineOutcome(
            task_id=task_request.task_id,
            token_id=token.token_id,
            success=False,
            final_state=token.lifecycle_state,
            final_patch=token.patch_hint,
            failure_reason=reason,
        )

    scheduler.assign_patch(token)
    store.save_token(token)
    store.save_snapshot(build_snapshot(task_request, token))
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

    result = runtime.execute(token)
    store.save_token(token)
    store.save_snapshot(build_snapshot(task_request, token))

    if result.success:
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
        return PipelineOutcome(
            task_id=task_request.task_id,
            token_id=token.token_id,
            success=True,
            final_state=token.lifecycle_state,
            final_patch=result.patch,
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

    recovery_engine.recover(token, result.failure_reason or "Execution failed.")
    store.save_token(token)
    store.save_snapshot(build_snapshot(task_request, token))
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

    resumed_result = runtime.execute(token)
    store.save_token(token)
    store.save_snapshot(build_snapshot(task_request, token))
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

    return PipelineOutcome(
        task_id=task_request.task_id,
        token_id=token.token_id,
        success=resumed_result.success,
        final_state=token.lifecycle_state,
        final_patch=resumed_result.patch,
        recovery_performed=True,
        failure_reason=None if resumed_result.success else resumed_result.failure_reason,
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
