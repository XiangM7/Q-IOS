from qios.sim.baselines import QIOSSimulationSystem
from qios.sim.environment import SimulationEnvironment
from qios.sim.runner import run_simulation
from qios.sim.workload import WorkloadGenerator


def test_runner_executes_small_simulation_and_writes_artifacts(tmp_path) -> None:
    output_dir = tmp_path / "runs" / "latest"

    result = run_simulation(
        num_tasks=10,
        failure_rate=0.2,
        systems="qios,direct,retry_only,static",
        seed=42,
        output_dir=output_dir,
    )

    assert len(result.metrics) == 4
    assert (output_dir / "metrics.csv").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "report.md").exists()


def test_qios_system_recovers_when_failure_rate_is_high() -> None:
    workload = WorkloadGenerator(
        num_tasks=12,
        failure_rate=0.7,
        sandbox_ratio=0.5,
        high_priority_ratio=0.3,
        seed=7,
    ).generate()
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.0,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=7,
    )

    metrics = QIOSSimulationSystem(environment).run(workload)

    assert metrics.recovered_tasks > 0
    assert metrics.reroute_count > 0
