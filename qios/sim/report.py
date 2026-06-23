from __future__ import annotations

import csv
import json
from pathlib import Path

from qios.sim.metrics import SimulationMetrics


def write_metrics_csv(output_dir: Path, metrics: list[SimulationMetrics]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "metrics.csv"
    fieldnames = [
        "system_name",
        "total_tasks",
        "completed_tasks",
        "failed_tasks",
        "generated_failure_tasks",
        "generated_policy_invalid_tasks",
        "generated_no_fallback_tasks",
        "primary_execution_attempts",
        "primary_execution_failures",
        "fallback_execution_attempts",
        "fallback_execution_failures",
        "congestion_failure_count",
        "runtime_failure_count",
        "recovered_tasks",
        "failed_recovery_count",
        "full_restart_count",
        "reroute_count",
        "fallback_dispatch_count",
        "quarantine_count",
        "max_reroute_exhausted_count",
        "policy_rejection_count",
        "phi_cache_hits",
        "phi_cache_updates",
        "modulation_profiles_created",
        "arbitration_accepts",
        "arbitration_rejects",
        "arbitration_defers",
        "arbitration_reroutes",
        "snapshots_created",
        "rollback_anchors_created",
        "replay_ledger_events",
        "local_reentry_count",
        "total_latency_ms",
        "completion_rate",
        "runtime_failure_rate",
        "policy_rejection_rate",
        "recovery_success_rate",
        "average_latency_ms",
        "p95_latency_ms",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in metrics:
            row = item.to_dict()
            writer.writerow({name: row[name] for name in fieldnames})

    return csv_path


def write_summary_json(
    output_dir: Path,
    settings: dict[str, object],
    workload_debug: dict[str, int],
    metrics: list[SimulationMetrics],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    payload = {
        "settings": settings,
        "workload_debug": workload_debug,
        "metrics": [item.to_dict() for item in metrics],
    }
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return summary_path


def write_report_markdown(
    output_dir: Path,
    settings: dict[str, object],
    workload_debug: dict[str, int],
    metrics: list[SimulationMetrics],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.md"
    report_path.write_text(_build_report(settings, workload_debug, metrics), encoding="utf-8")
    return report_path


def _build_report(
    settings: dict[str, object],
    workload_debug: dict[str, int],
    metrics: list[SimulationMetrics],
) -> str:
    lines = [
        "# Q-IOS Simulation Report",
        "",
        "## Experiment Settings",
        "",
    ]
    for key, value in settings.items():
        lines.append(f"- **{key}**: {value}")

    lines.extend(
        [
            "",
            "## Workload Debug Counters",
            "",
        ]
    )
    for key, value in workload_debug.items():
        lines.append(f"- **{key}**: {value}")

    lines.extend(
        [
            "",
            "## Comparison Table",
            "",
            "| System | Completion Rate | Runtime Failure Rate | Policy Rejection Rate | Recovery Success Rate | Failed Recoveries | Full Restarts | Reroutes | Fallback Dispatches | Quarantines | Max Reroute Exhausted | Avg Latency (ms) | P95 Latency (ms) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for item in metrics:
        lines.append(
            "| "
            f"{item.system_name} | "
            f"{item.completion_rate:.2%} | "
            f"{item.runtime_failure_rate:.2%} | "
            f"{item.policy_rejection_rate:.2%} | "
            f"{item.recovery_success_rate:.2%} | "
            f"{item.failed_recovery_count} | "
            f"{item.full_restart_count} | "
            f"{item.reroute_count} | "
            f"{item.fallback_dispatch_count} | "
            f"{item.quarantine_count} | "
            f"{item.max_reroute_exhausted_count} | "
            f"{item.average_latency_ms:.2f} | "
            f"{item.p95_latency_ms:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Execution Debug Counters",
            "",
            "| System | Primary Attempts | Primary Failures | Fallback Attempts | Fallback Failures | Congestion Failures | Max Reroute Exhausted |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in metrics:
        lines.append(
            "| "
            f"{item.system_name} | "
            f"{item.primary_execution_attempts} | "
            f"{item.primary_execution_failures} | "
            f"{item.fallback_execution_attempts} | "
            f"{item.fallback_execution_failures} | "
            f"{item.congestion_failure_count} | "
            f"{item.max_reroute_exhausted_count} |"
        )

    lines.extend(
        [
            "",
            "## Control Plane Counters",
            "",
            "| System | Phi Cache Hits | Phi Cache Updates | Modulation Profiles | Arbitration Accepts | Arbitration Rejects | Arbitration Defers | Arbitration Reroutes | Snapshots | Rollback Anchors | Replay Ledger Events | Local Reentry |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in metrics:
        lines.append(
            "| "
            f"{item.system_name} | "
            f"{item.phi_cache_hits} | "
            f"{item.phi_cache_updates} | "
            f"{item.modulation_profiles_created} | "
            f"{item.arbitration_accepts} | "
            f"{item.arbitration_rejects} | "
            f"{item.arbitration_defers} | "
            f"{item.arbitration_reroutes} | "
            f"{item.snapshots_created} | "
            f"{item.rollback_anchors_created} | "
            f"{item.replay_ledger_events} | "
            f"{item.local_reentry_count} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            _build_interpretation(metrics, workload_debug),
            "",
            "## Notes",
            "",
            "- `failure_rate` is applied during workload generation as primary-route failure pressure. It is not re-applied as an independent global failure draw on every attempt.",
            "- `fallback_failure_rate` only affects explicit fallback dispatch attempts.",
            "- Congestion primarily increases latency and only contributes mild, separately-counted failure pressure.",
            "- Policy rejections are counted separately from runtime failures and occur before execution begins.",
            "- Control plane counters reflect patent-aligned bookkeeping around cache feedback, modulation, arbitration, snapshotting, rollback anchors, and replay lineage.",
            "- Q-IOS recovery is bounded by `max_reroutes`, so recovery can still fail after repeated reroute or fallback failures.",
            "",
        ]
    )
    return "\n".join(lines)


def _build_interpretation(
    metrics: list[SimulationMetrics],
    workload_debug: dict[str, int],
) -> str:
    if not metrics:
        return "No systems were executed."

    best_completion = max(metrics, key=lambda item: item.completion_rate)
    lowest_latency = min(metrics, key=lambda item: item.average_latency_ms)
    qios_metrics = next((item for item in metrics if item.system_name == "qios"), None)

    statements = [
        f"`{best_completion.system_name}` achieved the highest completion rate at {best_completion.completion_rate:.2%}.",
        f"`{lowest_latency.system_name}` had the lowest average latency at {lowest_latency.average_latency_ms:.2f} ms.",
    ]

    if qios_metrics is not None:
        statements.append(
            f"`qios` completed {qios_metrics.completed_tasks} of {qios_metrics.total_tasks} tasks, "
            f"recovered {qios_metrics.recovered_tasks}, "
            f"failed recovery on {qios_metrics.failed_recovery_count}, "
            f"and exhausted reroutes {qios_metrics.max_reroute_exhausted_count} times."
        )
        statements.append(
            f"It also recorded {qios_metrics.modulation_profiles_created} modulation profiles, "
            f"{qios_metrics.arbitration_reroutes} arbitration-driven reroutes, "
            f"and {qios_metrics.replay_ledger_events} replay-ledger events."
        )
        statements.append(
            f"The generated workload contained {workload_debug.get('generated_failure_tasks', 0)} primary-failure tasks, "
            f"{workload_debug.get('generated_policy_invalid_tasks', 0)} policy-invalid tasks, "
            f"and {workload_debug.get('generated_no_fallback_tasks', 0)} no-fallback tasks."
        )

    return " ".join(statements)
