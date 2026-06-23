from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from qios.sim.baselines import (
    DirectExecutionBaseline,
    QIOSSimulationSystem,
    RetryOnlyBaseline,
    StaticRoutingBaseline,
)
from qios.sim.environment import SimulationEnvironment
from qios.sim.metrics import SimulationMetrics
from qios.sim.report import write_metrics_csv, write_report_markdown, write_summary_json
from qios.sim.workload import WorkloadGenerator, summarize_workload

app = typer.Typer(name="qios-sim", help="Run Q-IOS simulation benchmarks.")
console = Console()


@dataclass
class SimulationRunResult:
    settings: dict[str, object]
    workload_debug: dict[str, int]
    metrics: list[SimulationMetrics]
    output_dir: Path


def parse_systems(systems: str | list[str]) -> list[str]:
    if isinstance(systems, str):
        names = [name.strip() for name in systems.split(",") if name.strip()]
    else:
        names = [name.strip() for name in systems if name.strip()]

    valid = {"qios", "direct", "retry_only", "static"}
    invalid = [name for name in names if name not in valid]
    if invalid:
        raise ValueError(f"Unsupported systems requested: {', '.join(invalid)}")
    return names


def build_metrics_table(metrics: list[SimulationMetrics]) -> Table:
    table = Table(title="Simulation Comparison")
    table.add_column("System")
    table.add_column("Completion")
    table.add_column("Runtime Fail")
    table.add_column("Policy Reject")
    table.add_column("Recovery")
    table.add_column("Restarts")
    table.add_column("Reroutes")
    table.add_column("Fallbacks")
    table.add_column("Quarantines")
    table.add_column("Recoveries Failed")
    table.add_column("Exhausted")
    table.add_column("Avg ms")
    table.add_column("P95 ms")

    for item in metrics:
        table.add_row(
            item.system_name,
            f"{item.completion_rate:.2%}",
            f"{item.runtime_failure_rate:.2%}",
            f"{item.policy_rejection_rate:.2%}",
            f"{item.recovery_success_rate:.2%}",
            str(item.full_restart_count),
            str(item.reroute_count),
            str(item.fallback_dispatch_count),
            str(item.quarantine_count),
            str(item.failed_recovery_count),
            str(item.max_reroute_exhausted_count),
            f"{item.average_latency_ms:.2f}",
            f"{item.p95_latency_ms:.2f}",
        )

    return table


def run_simulation(
    *,
    num_tasks: int,
    failure_rate: float,
    systems: str | list[str],
    seed: int | None = None,
    fallback_failure_rate: float = 0.0,
    no_fallback_ratio: float = 0.0,
    policy_invalid_ratio: float = 0.0,
    sandbox_ratio: float = 0.4,
    high_priority_ratio: float = 0.3,
    patch_count: int = 4,
    congestion_rate: float = 0.1,
    max_reroutes: int = 1,
    base_latency_ms: float = 20.0,
    latency_jitter_ms: float = 5.0,
    output_dir: str | Path = Path("runs/latest"),
) -> SimulationRunResult:
    selected_systems = parse_systems(systems)
    workload = WorkloadGenerator(
        num_tasks=num_tasks,
        failure_rate=failure_rate,
        sandbox_ratio=sandbox_ratio,
        high_priority_ratio=high_priority_ratio,
        no_fallback_ratio=no_fallback_ratio,
        policy_invalid_ratio=policy_invalid_ratio,
        seed=seed,
    ).generate()
    workload_debug = summarize_workload(workload)

    environment_template = SimulationEnvironment(
        patch_count=patch_count,
        failure_rate=failure_rate,
        fallback_failure_rate=fallback_failure_rate,
        congestion_rate=congestion_rate,
        base_latency_ms=base_latency_ms,
        latency_jitter_ms=latency_jitter_ms,
        seed=seed,
    )

    metrics: list[SimulationMetrics] = []
    for system_name in selected_systems:
        task_batch = [task.model_copy(deep=True) for task in workload]
        if system_name == "qios":
            system = QIOSSimulationSystem(environment_template, max_reroutes=max_reroutes)
        elif system_name == "direct":
            system = DirectExecutionBaseline(environment_template)
        elif system_name == "retry_only":
            system = RetryOnlyBaseline(environment_template)
        else:
            system = StaticRoutingBaseline(environment_template)
        metrics.append(system.run(task_batch))

    resolved_output_dir = Path(output_dir)
    settings = {
        "num_tasks": num_tasks,
        "failure_rate": failure_rate,
        "fallback_failure_rate": fallback_failure_rate,
        "systems": selected_systems,
        "seed": seed,
        "no_fallback_ratio": no_fallback_ratio,
        "policy_invalid_ratio": policy_invalid_ratio,
        "sandbox_ratio": sandbox_ratio,
        "high_priority_ratio": high_priority_ratio,
        "patch_count": patch_count,
        "congestion_rate": congestion_rate,
        "max_reroutes": max_reroutes,
        "base_latency_ms": base_latency_ms,
        "latency_jitter_ms": latency_jitter_ms,
    }

    write_metrics_csv(resolved_output_dir, metrics)
    write_summary_json(resolved_output_dir, settings, workload_debug, metrics)
    write_report_markdown(resolved_output_dir, settings, workload_debug, metrics)

    return SimulationRunResult(
        settings=settings,
        workload_debug=workload_debug,
        metrics=metrics,
        output_dir=resolved_output_dir,
    )


@app.command()
def main(
    tasks: int = typer.Option(100, "--tasks", min=1, help="Number of synthetic tasks to generate."),
    failure_rate: float = typer.Option(0.1, "--failure-rate", min=0.0, max=1.0, help="Failure rate used for primary execution pressure in the generated workload."),
    fallback_failure_rate: float = typer.Option(0.0, "--fallback-failure-rate", min=0.0, max=1.0, help="Probability that explicit fallback execution fails."),
    no_fallback_ratio: float = typer.Option(0.0, "--no-fallback-ratio", min=0.0, max=1.0, help="Fraction of tasks generated without a fallback patch."),
    policy_invalid_ratio: float = typer.Option(0.0, "--policy-invalid-ratio", min=0.0, max=1.0, help="Fraction of tasks intentionally generated as policy-invalid."),
    congestion_rate: float = typer.Option(0.1, "--congestion-rate", min=0.0, max=1.0, help="Congestion level applied primarily to route latency and mildly to failure."),
    max_reroutes: int = typer.Option(1, "--max-reroutes", min=0, help="Maximum reroute attempts per Q-IOS task."),
    systems: str = typer.Option("qios,direct,retry_only,static", "--systems", help="Comma-separated systems to compare."),
    seed: int | None = typer.Option(42, "--seed", help="Seed for deterministic workload and environment sampling."),
) -> None:
    try:
        result = run_simulation(
            num_tasks=tasks,
            failure_rate=failure_rate,
            fallback_failure_rate=fallback_failure_rate,
            no_fallback_ratio=no_fallback_ratio,
            policy_invalid_ratio=policy_invalid_ratio,
            congestion_rate=congestion_rate,
            max_reroutes=max_reroutes,
            systems=systems,
            seed=seed,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    console.print(build_metrics_table(result.metrics))
    console.print(f"Artifacts written to `{result.output_dir}`.")


if __name__ == "__main__":
    app()
