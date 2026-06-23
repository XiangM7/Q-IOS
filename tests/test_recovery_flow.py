from qios.main import submit_task_request
from qios.models import PatchType, TaskRequest, TokenState
from qios.state_store import StateStore


def test_failing_task_triggers_recovery_and_reassignment(tmp_path) -> None:
    task = TaskRequest(
        objective="run fail simulation",
        priority=7,
        constraints={"sandbox_required": True},
        fallback=PatchType.FALLBACK.value,
    )
    store = StateStore(tmp_path / ".qios_state")

    outcome = submit_task_request(task, state_store=store)
    events = store.list_events(task.task_id)

    assert outcome.success is True
    assert outcome.recovery_performed is True
    assert outcome.final_state == TokenState.COMPLETED
    assert outcome.final_patch == PatchType.FALLBACK.value
    assert any(event.event_type == "execution_failed" for event in events)
    assert any(event.event_type == "recovery_reassigned" for event in events)
