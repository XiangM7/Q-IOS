from qios.models import TaskRequest
from qios.sim.baselines import QIOSSimulationSystem
from qios.sim.environment import SimulationEnvironment
from qios.sim.runner import run_simulation
from qios.sim.workload import WorkloadGenerator


def test_patch_health_decreases_after_failure_and_recovers_after_success() -> None:
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.0,
        fallback_failure_rate=0.0,
        congestion_rate=0.0,
        seed=11,
    )
    patch_id = sorted(environment.patches)[0]
    starting_health = environment.patches[patch_id].health_score

    environment.register_patch_outcome(patch_id, success=False)
    lower_health = environment.patches[patch_id].health_score
    environment.register_patch_outcome(patch_id, success=True)
    recovered_health = environment.patches[patch_id].health_score

    assert lower_health < starting_health
    assert recovered_health > lower_health


def test_patches_become_quarantined_after_repeated_failures() -> None:
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.0,
        fallback_failure_rate=0.0,
        congestion_rate=0.0,
        quarantine_threshold=3,
        seed=11,
    )
    patch_id = sorted(environment.patches)[0]

    environment.register_patch_outcome(patch_id, success=False)
    environment.register_patch_outcome(patch_id, success=False)
    just_quarantined = environment.register_patch_outcome(patch_id, success=False)

    assert just_quarantined is True
    assert environment.patches[patch_id].quarantined is True


def test_runner_executes_small_simulation_and_writes_artifacts(tmp_path) -> None:
    output_dir = tmp_path / "runs" / "latest"

    result = run_simulation(
        num_tasks=10,
        failure_rate=0.2,
        fallback_failure_rate=0.15,
        no_fallback_ratio=0.1,
        policy_invalid_ratio=0.1,
        congestion_rate=0.2,
        max_reroutes=2,
        systems="qios,direct,retry_only,static",
        seed=42,
        output_dir=output_dir,
    )

    assert len(result.metrics) == 4
    assert (output_dir / "metrics.csv").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "report.md").exists()


def test_qios_does_not_always_recover_when_fallback_failure_rate_is_high() -> None:
    workload = WorkloadGenerator(
        num_tasks=12,
        failure_rate=1.0,
        sandbox_ratio=0.5,
        high_priority_ratio=0.3,
        no_fallback_ratio=0.0,
        policy_invalid_ratio=0.0,
        seed=7,
    ).generate()
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.0,
        fallback_failure_rate=0.95,
        congestion_rate=0.1,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=7,
    )

    metrics = QIOSSimulationSystem(environment, max_reroutes=2).run(workload)

    assert metrics.completed_tasks < metrics.total_tasks
    assert metrics.failed_recovery_count > 0


def test_max_reroutes_prevents_infinite_recovery_loops() -> None:
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.0,
        fallback_failure_rate=1.0,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=5,
    )
    workload = [
        TaskRequest(
            task_id="reroute-exhaustion",
            objective="run fail simulation for reroute exhaustion",
            priority=7,
            constraints={"sandbox_required": True},
            fallback="fallback_patch",
        )
    ]

    metrics = QIOSSimulationSystem(environment, max_reroutes=1).run(workload)

    assert metrics.max_reroute_exhausted_count == 1
    assert metrics.reroute_count == 1


def test_policy_invalid_tasks_are_rejected_and_counted() -> None:
    workload = WorkloadGenerator(
        num_tasks=6,
        failure_rate=0.0,
        sandbox_ratio=0.5,
        high_priority_ratio=0.3,
        policy_invalid_ratio=1.0,
        seed=9,
    ).generate()
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.0,
        fallback_failure_rate=0.0,
        congestion_rate=0.0,
        seed=9,
    )

    metrics = QIOSSimulationSystem(environment, max_reroutes=2).run(workload)

    assert metrics.policy_rejection_count == 6
    assert metrics.completed_tasks == 0
    assert metrics.runtime_failure_count == 0


def test_no_fallback_tasks_can_fail_when_recovery_is_unavailable() -> None:
    workload = [
        TaskRequest(
            task_id="no-fallback-1",
            objective="run fail simulation for no fallback",
            priority=7,
            constraints={"sandbox_required": True},
            fallback=None,
        )
    ]
    environment = SimulationEnvironment(
        patch_count=2,
        failure_rate=0.0,
        fallback_failure_rate=0.0,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=21,
    )

    metrics = QIOSSimulationSystem(environment, max_reroutes=2).run(workload)

    assert metrics.failed_tasks == 1
    assert metrics.failed_recovery_count == 1
    assert metrics.completed_tasks == 0
