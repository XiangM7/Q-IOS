from __future__ import annotations

from qios.models import PatchType, PhiToken, TokenState


class Scheduler:
    def assign_patch(self, token: PhiToken) -> PhiToken:
        token.assigned_patch = token.patch_hint or PatchType.ANALYSIS.value
        token.lifecycle_state = TokenState.ASSIGNED
        return token
