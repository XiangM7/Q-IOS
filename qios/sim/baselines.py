from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from qios.main import submit_task_request
from qios.models import TaskRequest
from qios.sim.environment import SimulationEnvironment
from qios.sim.metrics import SimulationMetrics
from qios.state_store import StateStore


def _task_has_failure_marker(task: TaskRequest) -> bool:
    return "fail" in task.objective.lower()


class BaseSimulationSystem:
    system_name = "base"

    def __init__(self, environment: SimulationEnvironment) -> None:
        self.environment = environment.clone()

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        raise NotImplementedError

    def _attempt_fails(self, task: TaskRequest) -> bool:
        return _task_has_failure_marker(task) or self.environment.should_inject_failure()


class DirectExecutionBaseline(BaseSimulationSystem):
    system_name = "direct"

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)
        for task in tasks:
            latency_ms = self.environment.sample_latency_ms()
            completed = not self._attempt_fails(task)
            metrics.record_task(latency_ms=latency_ms, completed=completed)
        return metrics


class RetryOnlyBaseline(BaseSimulationSystem):
    system_name = "retry_only"

    def __init__(self, environment: SimulationEnvironment, max_retries: int = 2) -> None:
        super().__init__(environment)
        self.max_retries = max_retries

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)
        for task in tasks:
            latency_ms = 0.0
            restarts = 0
            completed = False

            for attempt in range(self.max_retries + 1):
                latency_ms += self.environment.sample_latency_ms()
                if not self._attempt_fails(task):
                    completed = True
                    break
                if attempt < self.max_retries:
                    restarts += 1

            metrics.record_task(
                latency_ms=latency_ms,
                completed=completed,
                full_restarts=restarts,
            )
        return metrics


class StaticRoutingBaseline(BaseSimulationSystem):
    system_name = "static"

    def __init__(self, environment: SimulationEnvironment, static_patch: str = "static_patch_0") -> None:
        super().__init__(environment)
        self.static_patch = static_patch

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)
        for task in tasks:
            latency_ms = self.environment.sample_latency_ms()
            first_attempt_failed = self._attempt_fails(task)
            completed = not first_attempt_failed
            restarts = 0

            if first_attempt_failed:
                restarts = 1
                latency_ms += self.environment.sample_latency_ms()
                completed = not self._attempt_fails(task)

            metrics.record_task(
                latency_ms=latency_ms,
                completed=completed,
                full_restarts=restarts,
            )
        return metrics


class QIOSSimulationSystem(BaseSimulationSystem):
    system_name = "qios"

    def run(self, tasks: list[TaskRequest]) -> SimulationMetrics:
        metrics = SimulationMetrics(system_name=self.system_name)

        with TemporaryDirectory(prefix="qios-sim-state-") as temp_dir:
            store = StateStore(Path(temp_dir) / ".qios_state")

            for task in tasks:
                task_copy = task.model_copy(deep=True)
                latency_ms = self.environment.sample_latency_ms()

                if self.environment.should_inject_failure() and "fail" not in task_copy.objective.lower():
                    task_copy.objective = f"{task_copy.objective} fail"

                outcome = submit_task_request(task_copy, state_store=store)
                events = store.list_events(task_copy.task_id)
                rerouted = any(event.event_type == "recovery_reassigned" for event in events)
                policy_rejected = any(event.event_type == "admissibility_rejected" for event in events)

                if outcome.recovery_performed:
                    latency_ms += self.environment.sample_latency_ms()

                metrics.record_task(
                    latency_ms=latency_ms,
                    completed=outcome.success,
                    recovered=outcome.recovery_performed and outcome.success,
                    reroutes=1 if rerouted else 0,
                    policy_rejected=policy_rejected,
                )

        return metrics
