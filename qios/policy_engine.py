from __future__ import annotations

from qios.models import PatchType, PhiToken


class PolicyEngine:
    def check_admissibility(self, token: PhiToken) -> tuple[bool, str]:
        if token.priority < 0 or token.priority > 10:
            return False, "Priority must be between 0 and 10."

        constraints = token.metadata.get("constraints", {})
        sandbox_required = bool(constraints.get("sandbox_required"))
        if token.role == "execution" and sandbox_required:
            if token.patch_hint != PatchType.SANDBOX.value:
                return False, "Execution tokens that require sandboxing must target sandbox_patch."

        return True, "Token admissible for execution."
