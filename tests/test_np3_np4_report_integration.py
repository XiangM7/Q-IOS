import json

from qios.sim.runner import run_simulation


def test_np3_np4_metrics_are_exposed_in_report_and_summary(tmp_path) -> None:
    output_dir = tmp_path / "runs" / "latest"

    result = run_simulation(
        num_tasks=12,
        failure_rate=0.3,
        fallback_failure_rate=0.15,
        no_fallback_ratio=0.1,
        policy_invalid_ratio=0.05,
        congestion_rate=0.2,
        max_reroutes=3,
        systems="qios,direct,retry_only,static",
        seed=42,
        output_dir=output_dir,
    )

    report_text = (output_dir / "report.md").read_text()
    summary = json.loads((output_dir / "summary.json").read_text())

    assert "NP3 / NP4 Control Plane Counters" in report_text
    assert "Health Score Updates" in report_text
    assert "Virtual Patches Created" in report_text
    assert "Routes Evaluated" in report_text
    assert "Dispatch Packets Created" in report_text
    assert "Remap Attempts" in report_text

    qios_metrics = next(item for item in summary["metrics"] if item["system_name"] == "qios")
    for key in [
        "health_score_updates",
        "telemetry_events",
        "virtual_patches_created",
        "routes_evaluated",
        "dispatch_packets_created",
        "remap_attempts",
    ]:
        assert key in qios_metrics

    assert qios_metrics["health_score_updates"] > 0
    assert qios_metrics["telemetry_events"] > 0
    assert qios_metrics["virtual_patches_created"] > 0
    assert qios_metrics["routes_evaluated"] > 0
    assert qios_metrics["dispatch_packets_created"] > 0
    assert qios_metrics["recovery_policy_decisions"] > 0

    qios_result = next(item for item in result.metrics if item.system_name == "qios")
    assert qios_result.average_route_score >= 0.0
    assert qios_result.average_health_score >= 0.0
