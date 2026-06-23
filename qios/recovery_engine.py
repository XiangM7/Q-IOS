from __future__ import annotations

from qios.models import PatchType, PhiToken, TokenState


class RecoveryEngine:
    def recover(self, token: PhiToken, failure_reason: str) -> PhiToken:
        token.lifecycle_state = TokenState.RECONFIGURING
        fallback_patch = token.fallback or PatchType.FALLBACK.value
        token.patch_hint = fallback_patch
        token.assigned_patch = fallback_patch
        token.phi_modulation = max(0.11, round(token.phi_modulation - 0.1, 2))
        token.metadata["recovery_reason"] = failure_reason
        token.lifecycle_state = TokenState.REASSIGNED
        return token
