from qios.control import PhiCache
from qios.control.modulation_profile import ModulationProfileGenerator
from qios.models import TaskRequest
from qios.structured_job import StructuredJobGenerator
from qios.token_engine import PhiTokenEngine


def test_modulation_profile_prefers_analysis_patch_for_analysis_role() -> None:
    task = TaskRequest(objective="analyze generated workload item 1", priority=8)
    token = PhiTokenEngine().create_token(StructuredJobGenerator().generate(task))
    cache = PhiCache()
    cache.update_success("analysis_patch", token.role, latency_ms=12.0, health_score=0.95)

    profile = ModulationProfileGenerator().generate(
        token,
        candidate_patch_ids=["analysis_patch", "sandbox_patch"],
        phi_cache=cache,
        patch_health={"analysis_patch": 0.92, "sandbox_patch": 0.84},
        patch_congestion={"analysis_patch": 0.02, "sandbox_patch": 0.08},
    )

    assert profile.selected_patch_id == "analysis_patch"
    assert profile.patch_scores[0].patch_id == "analysis_patch"


def test_modulation_profile_prefers_sandbox_patch_for_sandboxed_execution() -> None:
    task = TaskRequest(
        objective="run generated workload item 2",
        priority=9,
        constraints={"sandbox_required": True},
    )
    token = PhiTokenEngine().create_token(StructuredJobGenerator().generate(task))
    cache = PhiCache()

    profile = ModulationProfileGenerator().generate(
        token,
        candidate_patch_ids=["analysis_patch", "sandbox_patch"],
        phi_cache=cache,
        patch_health={"analysis_patch": 0.92, "sandbox_patch": 0.92},
        patch_congestion={"analysis_patch": 0.0, "sandbox_patch": 0.0},
    )

    assert profile.selected_patch_id == "sandbox_patch"
