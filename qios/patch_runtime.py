from __future__ import annotations

from qios.models import ExecutionResult, PatchType, PhiToken, TokenState


class PatchRuntime:
    def execute(self, token: PhiToken) -> ExecutionResult:
        objective = str(token.metadata.get("objective", "")).lower()
        active_patch = token.assigned_patch or token.patch_hint or PatchType.ANALYSIS.value

        if bool(token.metadata.get("sim_force_failure")):
            token.lifecycle_state = TokenState.FAILED
            return ExecutionResult(
                task_id=token.task_id,
                token_id=token.token_id,
                status=TokenState.FAILED,
                success=False,
                patch=active_patch,
                failure_reason="Simulated primary-route failure.",
            )

        if "fail" in objective and active_patch != PatchType.FALLBACK.value:
            token.lifecycle_state = TokenState.FAILED
            return ExecutionResult(
                task_id=token.task_id,
                token_id=token.token_id,
                status=TokenState.FAILED,
                success=False,
                patch=active_patch,
                failure_reason="Simulated runtime failure for fail-tagged objective.",
            )

        token.lifecycle_state = TokenState.COMPLETED
        return ExecutionResult(
            task_id=token.task_id,
            token_id=token.token_id,
            status=TokenState.COMPLETED,
            success=True,
            patch=active_patch,
            output=f"Execution completed on {active_patch}.",
        )
