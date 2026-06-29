# patch-local arbitration

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from qios.control.modulation_profile import ModulationProfile, PatchModulationScore


class ArbitrationDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"
    REROUTE = "REROUTE"
    QUARANTINE = "QUARANTINE"


class ArbitrationResult(BaseModel):
    token_id: str
    patch_id: str
    decision: ArbitrationDecision
    reason: str
    score: float
    alternative_patch_id: str | None = None

# threshold-based local arbitration algorithm
class PatchLocalArbitrator:
    def arbitrate(
        self,
        token,
        profile: ModulationProfile,
        patch_health: dict[str, float] | None = None,
        patch_congestion: dict[str, float] | None = None,
        quarantined_patches: set[str] | None = None,
    ) -> ArbitrationResult:
        selected_patch_id = profile.selected_patch_id or ""
        selected_score = self._find_score(profile.patch_scores, selected_patch_id)
        alternative_patch_id = self._find_alternative(profile.patch_scores, selected_patch_id)
        health = (patch_health or {}).get(selected_patch_id, 1.0)
        congestion = (patch_congestion or {}).get(selected_patch_id, 0.0)
        quarantined = selected_patch_id in (quarantined_patches or set())

        if quarantined:
            return ArbitrationResult(
                token_id=token.token_id,
                patch_id=selected_patch_id,
                decision=ArbitrationDecision.REROUTE if alternative_patch_id else ArbitrationDecision.REJECT,
                reason="Selected patch is quarantined.",
                score=selected_score,
                alternative_patch_id=alternative_patch_id,
            )

        if health < 0.25:
            return ArbitrationResult(
                token_id=token.token_id,
                patch_id=selected_patch_id,
                decision=ArbitrationDecision.QUARANTINE if not alternative_patch_id else ArbitrationDecision.REROUTE,
                reason="Patch health is critically low.",
                score=selected_score,
                alternative_patch_id=alternative_patch_id,
            )

        if health < 0.45:
            return ArbitrationResult(
                token_id=token.token_id,
                patch_id=selected_patch_id,
                decision=ArbitrationDecision.REROUTE if alternative_patch_id else ArbitrationDecision.REJECT,
                reason="Patch health is below arbitration threshold.",
                score=selected_score,
                alternative_patch_id=alternative_patch_id,
            )

        if congestion > 0.85:
            return ArbitrationResult(
                token_id=token.token_id,
                patch_id=selected_patch_id,
                decision=ArbitrationDecision.REROUTE if alternative_patch_id else ArbitrationDecision.DEFER,
                reason="Patch congestion is too high.",
                score=selected_score,
                alternative_patch_id=alternative_patch_id,
            )

        if selected_score >= 0.55:
            return ArbitrationResult(
                token_id=token.token_id,
                patch_id=selected_patch_id,
                decision=ArbitrationDecision.ACCEPT,
                reason="Patch accepted by local arbitration.",
                score=selected_score,
                alternative_patch_id=alternative_patch_id,
            )

        return ArbitrationResult(
            token_id=token.token_id,
            patch_id=selected_patch_id,
            decision=ArbitrationDecision.REROUTE if alternative_patch_id else ArbitrationDecision.REJECT,
            reason="Patch score is below arbitration acceptance threshold.",
            score=selected_score,
            alternative_patch_id=alternative_patch_id,
        )

    def _find_score(self, patch_scores: list[PatchModulationScore], patch_id: str) -> float:
        for item in patch_scores:
            if item.patch_id == patch_id:
                return item.final_score
        return 0.0

    def _find_alternative(
        self,
        patch_scores: list[PatchModulationScore],
        selected_patch_id: str,
    ) -> str | None:
        for item in patch_scores:
            if item.patch_id != selected_patch_id:
                return item.patch_id
        return None
