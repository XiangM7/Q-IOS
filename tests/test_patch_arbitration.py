from qios.control import ArbitrationDecision
from qios.control.modulation_profile import ModulationProfile, PatchModulationScore
from qios.control.patch_arbitration import PatchLocalArbitrator
from qios.models import TaskRequest
from qios.structured_job import StructuredJobGenerator
from qios.token_engine import PhiTokenEngine


def _build_token():
    task = TaskRequest(objective="analyze generated workload item 3", priority=8)
    return PhiTokenEngine().create_token(StructuredJobGenerator().generate(task))


def test_patch_arbitration_accepts_healthy_selected_patch() -> None:
    token = _build_token()
    profile = ModulationProfile(
        token_id=token.token_id,
        task_id=token.task_id,
        role=token.role,
        selected_patch_id="analysis_patch",
        patch_scores=[
            PatchModulationScore(
                patch_id="analysis_patch",
                role_score=1.0,
                priority_score=0.8,
                phi_cache_score=0.5,
                health_score=0.92,
                congestion_penalty=0.02,
                final_score=0.82,
                reason="healthy",
            )
        ],
    )

    result = PatchLocalArbitrator().arbitrate(
        token,
        profile,
        patch_health={"analysis_patch": 0.92},
        patch_congestion={"analysis_patch": 0.02},
    )

    assert result.decision == ArbitrationDecision.ACCEPT


def test_patch_arbitration_reroutes_quarantined_patch_to_alternative() -> None:
    token = _build_token()
    profile = ModulationProfile(
        token_id=token.token_id,
        task_id=token.task_id,
        role=token.role,
        selected_patch_id="analysis_patch",
        patch_scores=[
            PatchModulationScore(
                patch_id="analysis_patch",
                role_score=1.0,
                priority_score=0.8,
                phi_cache_score=0.5,
                health_score=0.9,
                congestion_penalty=0.02,
                final_score=0.84,
                reason="primary",
            ),
            PatchModulationScore(
                patch_id="sandbox_patch",
                role_score=0.5,
                priority_score=0.8,
                phi_cache_score=0.5,
                health_score=0.88,
                congestion_penalty=0.03,
                final_score=0.7,
                reason="alternate",
            ),
        ],
    )

    result = PatchLocalArbitrator().arbitrate(
        token,
        profile,
        patch_health={"analysis_patch": 0.9, "sandbox_patch": 0.88},
        patch_congestion={"analysis_patch": 0.02, "sandbox_patch": 0.03},
        quarantined_patches={"analysis_patch"},
    )

    assert result.decision == ArbitrationDecision.REROUTE
    assert result.alternative_patch_id == "sandbox_patch"
