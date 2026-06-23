from __future__ import annotations

import re

from qios.models import PatchType, StructuredJobModel, TaskRequest


class StructuredJobGenerator:
    def generate(self, task_request: TaskRequest) -> StructuredJobModel:
        return StructuredJobModel(
            task_id=task_request.task_id,
            objective=task_request.objective,
            entities=task_request.entities or self._infer_entities(task_request.objective),
            roles=[self._infer_role(task_request.objective)],
            constraints=task_request.constraints,
            output_condition=task_request.output_condition,
            priority=task_request.priority,
            fallback=task_request.fallback or PatchType.FALLBACK.value,
        )

    def _infer_role(self, objective: str) -> str:
        normalized = objective.lower()
        if "analyze" in normalized:
            return "analysis"
        if "run" in normalized or "execute" in normalized:
            return "execution"
        return "default_execution"

    def _infer_entities(self, objective: str) -> list[str]:
        words = re.findall(r"[A-Za-z0-9_]+", objective.lower())
        stopwords = {"the", "and", "for", "with", "into", "from", "task", "files"}
        entities = [word for word in words if word not in stopwords]
        return list(dict.fromkeys(entities[:4]))
