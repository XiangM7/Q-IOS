from qios.main import submit_task_request
from qios.models import PatchType, TaskRequest, TokenState
from qios.policy_engine import PolicyEngine
from qios.state_store import StateStore
from qios.structured_job import StructuredJobGenerator
from qios.token_engine import PhiTokenEngine


def test_task_can_be_converted_into_phi_token() -> None:
    task = TaskRequest(objective="analyze repository layout", priority=8)
    job = StructuredJobGenerator().generate(task)
    token = PhiTokenEngine().create_token(job)

    assert token.task_id == task.task_id
    assert token.role == "analysis"
    assert token.patch_hint == PatchType.ANALYSIS.value
    assert token.lifecycle_state == TokenState.PLANNED


def test_admissibility_check_works() -> None:
    task = TaskRequest(
        objective="run sandboxed process",
        priority=7,
        constraints={"sandbox_required": True},
    )
    token = PhiTokenEngine().create_token(StructuredJobGenerator().generate(task))
    token.patch_hint = PatchType.ANALYSIS.value

    allowed, reason = PolicyEngine().check_admissibility(token)

    assert not allowed
    assert "sandbox" in reason.lower()


def test_successful_task_completes(tmp_path) -> None:
    task = TaskRequest(
        objective="analyze project files",
        priority=8,
        constraints={"sandbox_required": False},
        fallback=PatchType.FALLBACK.value,
    )
    store = StateStore(tmp_path / ".qios_state")

    outcome = submit_task_request(task, state_store=store)
    snapshot = store.get_latest_snapshot(task.task_id)

    assert outcome.success is True
    assert outcome.final_state == TokenState.COMPLETED
    assert snapshot is not None
    assert snapshot.lifecycle_state == TokenState.COMPLETED
