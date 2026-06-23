from qios.control import PhiCache, ReplayLedger, RollbackAnchorManager
from qios.main import submit_task_request
from qios.models import PatchType, TaskRequest
from qios.state_store import StateStore


def test_submit_task_request_populates_control_plane_metadata_and_cache_hits(tmp_path) -> None:
    store = StateStore(tmp_path / ".qios_state")
    phi_cache = PhiCache()
    replay_ledger = ReplayLedger()
    rollback_manager = RollbackAnchorManager()

    first_task = TaskRequest(
        objective="analyze project files",
        priority=8,
        constraints={"sandbox_required": False},
        fallback=PatchType.FALLBACK.value,
    )
    first_outcome = submit_task_request(
        first_task,
        state_store=store,
        phi_cache=phi_cache,
        replay_ledger=replay_ledger,
        rollback_manager=rollback_manager,
    )
    second_task = TaskRequest(
        objective="analyze repository layout",
        priority=7,
        constraints={"sandbox_required": False},
        fallback=PatchType.FALLBACK.value,
    )
    second_outcome = submit_task_request(
        second_task,
        state_store=store,
        phi_cache=phi_cache,
        replay_ledger=replay_ledger,
        rollback_manager=rollback_manager,
    )
    snapshot = store.get_latest_snapshot(second_task.task_id)

    assert first_outcome.success is True
    assert first_outcome.control_metrics["modulation_profiles_created"] >= 1
    assert second_outcome.control_metrics["phi_cache_hits"] >= 1
    assert "replay_lineage" in second_outcome.control_metadata
    assert snapshot is not None
    assert "control_plane" in snapshot.payload
    assert snapshot.payload["control_plane"]["rollback_anchor_id"] is not None


def test_submit_task_request_tracks_recovery_control_metadata(tmp_path) -> None:
    store = StateStore(tmp_path / ".qios_state")
    task = TaskRequest(
        objective="run fail simulation",
        priority=7,
        constraints={"sandbox_required": True},
        fallback=PatchType.FALLBACK.value,
    )

    outcome = submit_task_request(task, state_store=store)
    snapshot = store.get_latest_snapshot(task.task_id)

    assert outcome.success is True
    assert outcome.recovery_performed is True
    assert outcome.final_patch == PatchType.FALLBACK.value
    assert outcome.control_metrics["local_reentry_count"] >= 1
    assert outcome.control_metrics["phi_cache_updates"] >= 3
    assert outcome.control_metadata["failed_patches"]
    assert snapshot is not None
    assert snapshot.payload["control_plane"]["patch_id"] == PatchType.FALLBACK.value
