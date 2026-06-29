# job → ϕ-token

from __future__ import annotations

from qios.models import PatchType, PhiToken, StructuredJobModel, TokenState


class PhiTokenEngine:
    # 从 StructuredJob 里提取 role，根据 role 和 constraints 推断 patch_hint。
    # 根据 priority 生成 phi_modulation，然后创建 PhiToken。
    # NP1 FIG. 2 / Operation 205:
    # Creates a phi-token from the current job description.
    # NP1 FIG. 2 / Operation 210:
    # Extracts identity/context metadata and the role tag from the structured job.
    # NP1 FIG. 2 / Operation 215:
    # Determines execution-localization fields such as patch hint, priority, and fallback.
    # NP1 FIG. 1 / Block 130:
    # Acts as the simplified token parser / metadata extractor for runtime control.
    # NP1 FIG. 1 / Block 140:
    # Prepares a rule-based phi-to-weight value through `phi_modulation`.
    def create_token(self, structured_job: StructuredJobModel) -> PhiToken:
        role = structured_job.roles[0] if structured_job.roles else "default_execution"
        patch_hint = self._infer_patch_hint(role, structured_job.constraints)
        phi_modulation = min(1.0, max(0.1, structured_job.priority / 10))

        return PhiToken(
            task_id=structured_job.task_id,
            role=role,
            priority=structured_job.priority,
            patch_hint=patch_hint,
            fallback=structured_job.fallback,
            lifecycle_state=TokenState.PLANNED,
            phi_modulation=phi_modulation,
            metadata={
                "objective": structured_job.objective,
                "constraints": structured_job.constraints,
                "entities": structured_job.entities,
                "output_condition": structured_job.output_condition,
            },
        )

    # NP1 FIG. 2 / Operation 215:
    # Determines execution-localization fields by mapping role and constraints
    # to patch destination hints that the later control plane can refine.
    def _infer_patch_hint(self, role: str, constraints: dict[str, object]) -> str | None:
        if constraints.get("sandbox_required"):
            return PatchType.SANDBOX.value
        if role == "analysis":
            return PatchType.ANALYSIS.value
        if role == "execution":
            return PatchType.SANDBOX.value
        return None
