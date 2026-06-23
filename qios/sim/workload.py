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
        seed: int | None = None,
    ) -> None:
        self.num_tasks = num_tasks
        self.failure_rate = failure_rate
        self.sandbox_ratio = sandbox_ratio
        self.high_priority_ratio = high_priority_ratio
        self.seed = seed
        self._rng = random.Random(seed)

    def generate(self) -> list[TaskRequest]:
        tasks: list[TaskRequest] = []
        seed_tag = self.seed if self.seed is not None else "default"

        for index in range(self.num_tasks):
            should_fail = self._rng.random() < self.failure_rate
            sandbox_required = self._rng.random() < self.sandbox_ratio
            high_priority = self._rng.random() < self.high_priority_ratio
            use_analysis_objective = self._rng.random() < 0.5 and not should_fail

            if should_fail:
                objective = f"run fail simulation for workload item {index}"
            elif use_analysis_objective:
                objective = f"analyze generated workload item {index}"
            else:
                objective = f"run generated workload item {index}"

            priority = self._rng.randint(8, 10) if high_priority else self._rng.randint(3, 7)
            tasks.append(
                TaskRequest(
                    task_id=f"workload-task-{seed_tag}-{index}",
                    objective=objective,
                    priority=priority,
                    constraints={"sandbox_required": sandbox_required},
                    fallback=PatchType.FALLBACK.value,
                )
            )

        return tasks
