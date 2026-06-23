from __future__ import annotations

from pydantic import BaseModel, Field

from qios.control.phi_cache import PhiCache


class PatchModulationScore(BaseModel):
    patch_id: str
    role_score: float
    priority_score: float
    phi_cache_score: float
    health_score: float
    congestion_penalty: float
    final_score: float
    reason: str


class ModulationProfile(BaseModel):
    token_id: str
    task_id: str
    role: str
    patch_scores: list[PatchModulationScore] = Field(default_factory=list)
    selected_patch_id: str | None = None


class ModulationProfileGenerator:
    def generate(
        self,
        token,
        candidate_patch_ids: list[str],
        phi_cache: PhiCache,
        patch_health: dict[str, float] | None = None,
        patch_congestion: dict[str, float] | None = None,
    ) -> ModulationProfile:
        scores: list[PatchModulationScore] = []

        for patch_id in candidate_patch_ids:
            role_score = self._role_score(token, patch_id)
            priority_score = min(1.0, max(0.0, token.priority / 10))
            phi_cache_score = phi_cache.get_preference_score(patch_id, token.role)
            health_score = (patch_health or {}).get(patch_id, 1.0)
            congestion_penalty = (patch_congestion or {}).get(patch_id, 0.0)

            final_score = (
                (role_score * 0.45)
                + (priority_score * 0.1)
                + (phi_cache_score * 0.2)
                + (health_score * 0.25)
                - (congestion_penalty * 0.15)
            )
            final_score = round(min(1.0, max(0.0, final_score)), 3)
            scores.append(
                PatchModulationScore(
                    patch_id=patch_id,
                    role_score=round(role_score, 3),
                    priority_score=round(priority_score, 3),
                    phi_cache_score=round(phi_cache_score, 3),
                    health_score=round(health_score, 3),
                    congestion_penalty=round(congestion_penalty, 3),
                    final_score=final_score,
                    reason=(
                        f"role={role_score:.2f}, priority={priority_score:.2f}, "
                        f"cache={phi_cache_score:.2f}, health={health_score:.2f}, "
                        f"congestion={congestion_penalty:.2f}"
                    ),
                )
            )

        ordered = sorted(scores, key=lambda item: (-item.final_score, item.patch_id))
        return ModulationProfile(
            token_id=token.token_id,
            task_id=token.task_id,
            role=token.role,
            patch_scores=ordered,
            selected_patch_id=ordered[0].patch_id if ordered else None,
        )

    def _role_score(self, token, patch_id: str) -> float:
        patch_name = patch_id.lower()
        sandbox_required = bool(token.metadata.get("constraints", {}).get("sandbox_required"))

        if token.role == "analysis":
            if "analysis_patch" in patch_name:
                return 1.0
            if "sandbox_patch" in patch_name:
                return 0.55
            if "fallback_patch" in patch_name:
                return 0.3
            return 0.35

        if token.role == "execution" or sandbox_required:
            if "sandbox_patch" in patch_name:
                return 1.0
            if "analysis_patch" in patch_name:
                return 0.45
            if "fallback_patch" in patch_name:
                return 0.35
            return 0.4

        if "sandbox_patch" in patch_name:
            return 0.85
        if "analysis_patch" in patch_name:
            return 0.8
        if "fallback_patch" in patch_name:
            return 0.3
        return 0.35
