from qios.control import ReplayLedger, RollbackAnchorManager, SnapshotPackageBuilder
from qios.models import TaskRequest
from qios.structured_job import StructuredJobGenerator
from qios.token_engine import PhiTokenEngine


def _build_token():
    task = TaskRequest(objective="run generated workload item 4", priority=7)
    return PhiTokenEngine().create_token(StructuredJobGenerator().generate(task))


def test_snapshot_package_builder_captures_anchor_and_lineage() -> None:
    token = _build_token()
    snapshot = SnapshotPackageBuilder().build(
        token=token,
        patch_id="sandbox_patch",
        rollback_anchor_id="anchor-1",
        replay_lineage=["token_created:sandbox_patch"],
        memory_isolation_label="sandbox_patch",
        metadata={"phase": "planned"},
    )

    assert snapshot.patch_id == "sandbox_patch"
    assert snapshot.rollback_anchor_id == "anchor-1"
    assert snapshot.replay_lineage == ["token_created:sandbox_patch"]


def test_replay_ledger_tracks_failed_and_successful_patches() -> None:
    token = _build_token()
    ledger = ReplayLedger()
    ledger.append_event(token.task_id, token.token_id, "primary_execution_failed", patch_id="sandbox_patch")
    ledger.append_event(token.task_id, token.token_id, "recovery_execution_completed", patch_id="fallback_patch")

    assert ledger.get_failed_patches(token.token_id) == {"sandbox_patch"}
    assert ledger.get_last_successful_patch(token.token_id) == "fallback_patch"
    assert ledger.get_replay_lineage(token.token_id) == [
        "primary_execution_failed:sandbox_patch",
        "recovery_execution_completed:fallback_patch",
    ]


def test_rollback_anchor_manager_returns_latest_anchor() -> None:
    token = _build_token()
    manager = RollbackAnchorManager()
    first = manager.create_anchor(token.task_id, token.token_id, "sandbox_patch", "planned")
    latest = manager.create_anchor(token.task_id, token.token_id, "fallback_patch", "recovery")

    assert manager.get_anchor(first.anchor_id) == first
    assert manager.get_latest_anchor(token.token_id) == latest
    assert manager.list_anchors(token.token_id) == [first, latest]
