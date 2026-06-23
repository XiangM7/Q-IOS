from __future__ import annotations

import random

from qios.models import PatchType, TaskRequest


class WorkloadGenerator:
    def __init__(
        self,
        num_tasks: int,
        failure_rate: float,
        sandbox_ratio: float,
        high_priority_ratio: float,
        no_fallback_ratio: float = 0.0,
        policy_invalid_ratio: float = 0.0,
        seed: int | None = None,
    ) -> None:
        self.num_tasks = num_tasks
        self.failure_rate = failure_rate
        self.sandbox_ratio = sandbox_ratio
        self.high_priority_ratio = high_priority_ratio
        self.no_fallback_ratio = no_fallback_ratio
        self.policy_invalid_ratio = policy_invalid_ratio
        self.seed = seed
        self._rng = random.Random(seed)

    def generate(self) -> list[TaskRequest]:
        tasks: list[TaskRequest] = []
        seed_tag = self.seed if self.seed is not None else "default"

        for index in range(self.num_tasks):
            primary_failure = self._rng.random() < self.failure_rate
            sandbox_required = self._rng.random() < self.sandbox_ratio
            high_priority = self._rng.random() < self.high_priority_ratio
            has_no_fallback = self._rng.random() < self.no_fallback_ratio
            policy_invalid = self._rng.random() < self.policy_invalid_ratio
            use_analysis_objective = self._rng.random() < 0.5

            objective = (
                f"analyze generated workload item {index}"
                if use_analysis_objective
                else f"run generated workload item {index}"
            )

            constraints: dict[str, object] = {
                "sandbox_required": sandbox_required,
                "sim_primary_failure": primary_failure,
            }
            priority = self._rng.randint(8, 10) if high_priority else self._rng.randint(3, 7)

            if policy_invalid:
                invalid_mode = self._rng.choice(
                    ["priority_high", "priority_low", "sandbox_incompatible_patch"]
                )
                if invalid_mode == "priority_high":
                    priority = 11 + self._rng.randint(0, 2)
                elif invalid_mode == "priority_low":
                    priority = -1 - self._rng.randint(0, 2)
                else:
                    objective = f"run invalid sandbox workload item {index}"
                    constraints["sandbox_required"] = True
                    constraints["force_invalid_patch_hint"] = True
                constraints["policy_invalid_reason"] = invalid_mode

            tasks.append(
                TaskRequest(
                    task_id=f"workload-task-{seed_tag}-{index}",
                    objective=objective,
                    priority=priority,
                    constraints=constraints,
                    fallback=None if has_no_fallback else PatchType.FALLBACK.value,
                )
            )

        return tasks


def summarize_workload(tasks: list[TaskRequest]) -> dict[str, int]:
    return {
        "generated_failure_tasks": sum(
            bool(task.constraints.get("sim_primary_failure")) for task in tasks
        ),
        "generated_policy_invalid_tasks": sum(
            task.priority < 0
            or task.priority > 10
            or bool(task.constraints.get("force_invalid_patch_hint"))
            for task in tasks
        ),
        "generated_no_fallback_tasks": sum(task.fallback is None for task in tasks),
    }
