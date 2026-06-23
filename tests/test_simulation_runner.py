import json

from qios.models import TaskRequest
from qios.sim.baselines import DirectExecutionBaseline, QIOSSimulationSystem
from qios.sim.environment import SimulationEnvironment
from qios.sim.runner import run_simulation
from qios.sim.workload import WorkloadGenerator, summarize_workload


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

    summary = json.loads((output_dir / "summary.json").read_text())
    assert "workload_debug" in summary
    assert "generated_failure_tasks" in summary["workload_debug"]
    assert "primary_execution_attempts" in summary["metrics"][0]
    assert "modulation_profiles_created" in summary["metrics"][0]
    assert "replay_ledger_events" in summary["metrics"][0]


def test_direct_baseline_completion_is_reasonable_for_seeded_workload() -> None:
    tasks = WorkloadGenerator(
        num_tasks=1000,
        failure_rate=0.3,
        sandbox_ratio=0.4,
        high_priority_ratio=0.3,
        no_fallback_ratio=0.1,
        policy_invalid_ratio=0.05,
        seed=42,
    ).generate()
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.3,
        fallback_failure_rate=0.15,
        congestion_rate=0.2,
        base_latency_ms=20.0,
        latency_jitter_ms=5.0,
        seed=42,
    )

    metrics = DirectExecutionBaseline(environment).run(tasks)

    assert 0.55 <= metrics.completion_rate <= 0.70
    assert 0.03 <= metrics.policy_rejection_rate <= 0.07


def test_policy_invalid_count_is_close_to_requested_ratio() -> None:
    tasks = WorkloadGenerator(
        num_tasks=1000,
        failure_rate=0.3,
        sandbox_ratio=0.4,
        high_priority_ratio=0.3,
        no_fallback_ratio=0.1,
        policy_invalid_ratio=0.05,
        seed=42,
    ).generate()
    summary = summarize_workload(tasks)

    assert 30 <= summary["generated_policy_invalid_tasks"] <= 70


def test_congestion_increases_latency() -> None:
    tasks = WorkloadGenerator(
        num_tasks=100,
        failure_rate=0.0,
        sandbox_ratio=0.4,
        high_priority_ratio=0.3,
        seed=12,
    ).generate()
    low_congestion = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.0,
        fallback_failure_rate=0.0,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=12,
    )
    high_congestion = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.0,
        fallback_failure_rate=0.0,
        congestion_rate=0.4,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=12,
    )

    low_metrics = DirectExecutionBaseline(low_congestion).run(tasks)
    high_metrics = DirectExecutionBaseline(high_congestion).run(tasks)

    assert high_metrics.average_latency_ms > low_metrics.average_latency_ms


def test_fallback_failure_rate_only_affects_fallback_attempts() -> None:
    workload = [
        TaskRequest(
            task_id="fallback-effect",
            objective="run generated fallback effect item",
            priority=7,
            constraints={"sandbox_required": True, "sim_primary_failure": True},
            fallback="fallback_patch",
        )
    ]
    base_environment = dict(
        patch_count=4,
        failure_rate=0.3,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=7,
    )

    low_fallback = QIOSSimulationSystem(
        SimulationEnvironment(fallback_failure_rate=0.0, **base_environment),
        max_reroutes=1,
    ).run(workload)
    high_fallback = QIOSSimulationSystem(
        SimulationEnvironment(fallback_failure_rate=1.0, **base_environment),
        max_reroutes=1,
    ).run(workload)

    assert low_fallback.primary_execution_failures == high_fallback.primary_execution_failures == 1
    assert low_fallback.fallback_execution_attempts == high_fallback.fallback_execution_attempts == 1
    assert low_fallback.fallback_execution_failures == 0
    assert high_fallback.fallback_execution_failures == 1


def test_qios_does_not_always_recover_when_fallback_failure_rate_is_high() -> None:
    workload = [
        TaskRequest(
            task_id=f"fallback-hard-{index}",
            objective=f"run generated fallback hard item {index}",
            priority=7,
            constraints={"sandbox_required": True, "sim_primary_failure": True},
            fallback="fallback_patch",
        )
        for index in range(8)
    ]
    environment = SimulationEnvironment(
        patch_count=3,
        failure_rate=0.8,
        fallback_failure_rate=1.0,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=7,
    )

    metrics = QIOSSimulationSystem(environment, max_reroutes=1).run(workload)

    assert metrics.completed_tasks < metrics.total_tasks
    assert metrics.failed_recovery_count > 0


def test_max_reroutes_prevents_infinite_recovery_loops() -> None:
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=1.0,
        fallback_failure_rate=1.0,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=5,
    )
    workload = [
        TaskRequest(
            task_id="reroute-exhaustion",
            objective="run generated reroute exhaustion item",
            priority=7,
            constraints={"sandbox_required": True, "sim_primary_failure": True},
            fallback="fallback_patch",
        )
    ]

    metrics = QIOSSimulationSystem(environment, max_reroutes=1).run(workload)

    assert metrics.max_reroute_exhausted_count == 1
    assert metrics.reroute_count == 1


def test_policy_invalid_tasks_are_rejected_and_counted() -> None:
    workload = WorkloadGenerator(
        num_tasks=100,
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

    assert metrics.policy_rejection_count == 100
    assert metrics.completed_tasks == 0
    assert metrics.runtime_failure_count == 0


def test_no_fallback_tasks_can_recover_when_alternate_route_exists() -> None:
    workload = [
        TaskRequest(
            task_id="no-fallback-recover",
            objective="run generated no fallback recover item",
            priority=7,
            constraints={"sandbox_required": True, "sim_primary_failure": True},
            fallback=None,
        )
    ]
    environment = SimulationEnvironment(
        patch_count=2,
        failure_rate=0.3,
        fallback_failure_rate=0.0,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=21,
    )

    metrics = QIOSSimulationSystem(environment, max_reroutes=2).run(workload)

    assert metrics.completed_tasks == 1
    assert metrics.failed_tasks == 0


def test_no_fallback_tasks_fail_when_no_alternate_route_exists() -> None:
    workload = [
        TaskRequest(
            task_id="no-fallback-fail",
            objective="run generated no fallback fail item",
            priority=7,
            constraints={"sandbox_required": True, "sim_primary_failure": True},
            fallback=None,
        )
    ]
    environment = SimulationEnvironment(
        patch_count=1,
        failure_rate=0.3,
        fallback_failure_rate=0.0,
        congestion_rate=0.0,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=21,
    )

    metrics = QIOSSimulationSystem(environment, max_reroutes=2).run(workload)

    assert metrics.completed_tasks == 0
    assert metrics.failed_recovery_count == 1


def test_qios_simulation_records_control_plane_counters() -> None:
    workload = [
        TaskRequest(
            task_id="control-plane-recovery",
            objective="run generated control plane recovery item",
            priority=8,
            constraints={"sandbox_required": True, "sim_primary_failure": True},
            fallback="fallback_patch",
        )
    ]
    environment = SimulationEnvironment(
        patch_count=4,
        failure_rate=0.3,
        fallback_failure_rate=0.0,
        congestion_rate=0.1,
        base_latency_ms=20.0,
        latency_jitter_ms=0.0,
        seed=42,
    )

    metrics = QIOSSimulationSystem(environment, max_reroutes=2).run(workload)

    assert metrics.modulation_profiles_created >= 1
    assert metrics.snapshots_created >= 1
    assert metrics.replay_ledger_events >= 1
    assert metrics.local_reentry_count >= 1
