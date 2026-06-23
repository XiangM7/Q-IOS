import pytest

from qios.sim.metrics import SimulationMetrics
from qios.sim.workload import WorkloadGenerator


def test_workload_generation_is_deterministic_with_seed() -> None:
    generator_one = WorkloadGenerator(
        num_tasks=5,
        failure_rate=0.4,
        sandbox_ratio=0.5,
        high_priority_ratio=0.3,
        seed=42,
    )
    generator_two = WorkloadGenerator(
        num_tasks=5,
        failure_rate=0.4,
        sandbox_ratio=0.5,
        high_priority_ratio=0.3,
        seed=42,
    )

    workload_one = [task.model_dump(mode="json") for task in generator_one.generate()]
    workload_two = [task.model_dump(mode="json") for task in generator_two.generate()]

    assert workload_one == workload_two


def test_metrics_compute_completion_rate_correctly() -> None:
    metrics = SimulationMetrics(system_name="demo")
    metrics.record_task(latency_ms=10.0, completed=True)
    metrics.record_task(latency_ms=12.0, completed=True)
    metrics.record_task(latency_ms=18.0, completed=False)

    assert metrics.completion_rate == pytest.approx(2 / 3)


def test_metrics_compute_p95_latency() -> None:
    metrics = SimulationMetrics(system_name="demo")
    for latency in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        metrics.record_task(latency_ms=float(latency), completed=True)

    assert metrics.p95_latency_ms == pytest.approx(100.0)
