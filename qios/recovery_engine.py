from __future__ import annotations

from qios.models import PatchType, PhiToken, TokenState


class RecoveryEngine:
    def recover(
        self,
        token: PhiToken,
        failure_reason: str,
        *,
        rollback_anchor_id: str | None = None,
        replay_lineage: list[str] | None = None,
        failed_patches: list[str] | None = None,
        alternative_patch: str | None = None,
    ) -> PhiToken:
        token.lifecycle_state = TokenState.RECONFIGURING
        fallback_patch = alternative_patch or token.fallback or PatchType.FALLBACK.value
        token.patch_hint = fallback_patch
        token.assigned_patch = fallback_patch
        token.phi_modulation = max(0.11, round(token.phi_modulation - 0.1, 2))
        token.metadata["recovery_reason"] = failure_reason
        if rollback_anchor_id is not None:
            token.metadata["rollback_anchor_id"] = rollback_anchor_id
        if replay_lineage is not None:
            token.metadata["replay_lineage"] = list(replay_lineage)
        if failed_patches is not None:
            token.metadata["failed_patches"] = list(failed_patches)
        if alternative_patch is not None:
            token.metadata["recovery_target_patch"] = alternative_patch
        token.lifecycle_state = TokenState.REASSIGNED
        return token
