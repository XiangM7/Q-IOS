from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil


@dataclass
class SimulationMetrics:
    system_name: str
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    generated_failure_tasks: int = 0
    generated_policy_invalid_tasks: int = 0
    generated_no_fallback_tasks: int = 0
    primary_execution_attempts: int = 0
    primary_execution_failures: int = 0
    fallback_execution_attempts: int = 0
    fallback_execution_failures: int = 0
    congestion_failure_count: int = 0
    runtime_failure_count: int = 0
    recovered_tasks: int = 0
    failed_recovery_count: int = 0
    full_restart_count: int = 0
    reroute_count: int = 0
    fallback_dispatch_count: int = 0
    quarantine_count: int = 0
    max_reroute_exhausted_count: int = 0
    policy_rejection_count: int = 0
    phi_cache_hits: int = 0
    phi_cache_updates: int = 0
    modulation_profiles_created: int = 0
    arbitration_accepts: int = 0
    arbitration_rejects: int = 0
    arbitration_defers: int = 0
    arbitration_reroutes: int = 0
    snapshots_created: int = 0
    rollback_anchors_created: int = 0
    replay_ledger_events: int = 0
    local_reentry_count: int = 0
    health_score_updates: int = 0
    telemetry_events: int = 0
    recovery_policy_decisions: int = 0
    recovery_policy_reroutes: int = 0
    recovery_policy_fallbacks: int = 0
    recovery_policy_failures: int = 0
    virtual_patches_created: int = 0
    routes_evaluated: int = 0
    dispatch_packets_created: int = 0
    remap_attempts: int = 0
    remap_successes: int = 0
    remap_failures: int = 0
    route_score_total: float = 0.0
    route_score_count: int = 0
    health_score_total: float = 0.0
    health_score_count: int = 0
    quarantined_patch_count: int = 0
    total_latency_ms: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)

    def attach_workload_debug(
        self,
        *,
        generated_failure_tasks: int,
        generated_policy_invalid_tasks: int,
        generated_no_fallback_tasks: int,
    ) -> None:
        self.generated_failure_tasks = generated_failure_tasks
        self.generated_policy_invalid_tasks = generated_policy_invalid_tasks
        self.generated_no_fallback_tasks = generated_no_fallback_tasks

    def record_execution_attempt(
        self,
        *,
        is_fallback: bool,
        failed: bool,
        congestion_failure: bool = False,
    ) -> None:
        if is_fallback:
            self.fallback_execution_attempts += 1
            if failed:
                self.fallback_execution_failures += 1
        else:
            self.primary_execution_attempts += 1
            if failed:
                self.primary_execution_failures += 1
        if congestion_failure:
            self.congestion_failure_count += 1

    def record_control_plane(self, control_metrics: dict[str, int]) -> None:
        self.phi_cache_hits += control_metrics.get("phi_cache_hits", 0)
        self.phi_cache_updates += control_metrics.get("phi_cache_updates", 0)
        self.modulation_profiles_created += control_metrics.get("modulation_profiles_created", 0)
        self.arbitration_accepts += control_metrics.get("arbitration_accepts", 0)
        self.arbitration_rejects += control_metrics.get("arbitration_rejects", 0)
        self.arbitration_defers += control_metrics.get("arbitration_defers", 0)
        self.arbitration_reroutes += control_metrics.get("arbitration_reroutes", 0)
        self.snapshots_created += control_metrics.get("snapshots_created", 0)
        self.rollback_anchors_created += control_metrics.get("rollback_anchors_created", 0)
        self.replay_ledger_events += control_metrics.get("replay_ledger_events", 0)
        self.local_reentry_count += control_metrics.get("local_reentry_count", 0)
        self.health_score_updates += control_metrics.get("health_score_updates", 0)
        self.telemetry_events += control_metrics.get("telemetry_events", 0)
        self.recovery_policy_decisions += control_metrics.get("recovery_policy_decisions", 0)
        self.recovery_policy_reroutes += control_metrics.get("recovery_policy_reroutes", 0)
        self.recovery_policy_fallbacks += control_metrics.get("recovery_policy_fallbacks", 0)
        self.recovery_policy_failures += control_metrics.get("recovery_policy_failures", 0)
        self.virtual_patches_created += control_metrics.get("virtual_patches_created", 0)
        self.routes_evaluated += control_metrics.get("routes_evaluated", 0)
        self.dispatch_packets_created += control_metrics.get("dispatch_packets_created", 0)
        self.remap_attempts += control_metrics.get("remap_attempts", 0)
        self.remap_successes += control_metrics.get("remap_successes", 0)
        self.remap_failures += control_metrics.get("remap_failures", 0)
        self.route_score_total = round(self.route_score_total + control_metrics.get("route_score_total", 0.0), 6)
        self.route_score_count += control_metrics.get("route_score_count", 0)
        self.health_score_total = round(self.health_score_total + control_metrics.get("health_score_total", 0.0), 6)
        self.health_score_count += control_metrics.get("health_score_count", 0)
        self.quarantined_patch_count = max(
            self.quarantined_patch_count,
            control_metrics.get("quarantined_patch_count", 0),
        )

    def record_task(
        self,
        *,
        latency_ms: float,
        completed: bool,
        runtime_failed: bool = False,
        policy_rejected: bool = False,
        recovered: bool = False,
        failed_recovery: bool = False,
        full_restarts: int = 0,
        reroutes: int = 0,
        fallback_dispatches: int = 0,
        quarantines: int = 0,
        max_reroute_exhausted: bool = False,
    ) -> None:
        self.total_tasks += 1
        if completed:
            self.completed_tasks += 1
        else:
            self.failed_tasks += 1
        if runtime_failed:
            self.runtime_failure_count += 1
        if policy_rejected:
            self.policy_rejection_count += 1
        if recovered:
            self.recovered_tasks += 1
        if failed_recovery:
            self.failed_recovery_count += 1
        if max_reroute_exhausted:
            self.max_reroute_exhausted_count += 1
        self.full_restart_count += full_restarts
        self.reroute_count += reroutes
        self.fallback_dispatch_count += fallback_dispatches
        self.quarantine_count += quarantines
        self.total_latency_ms = round(self.total_latency_ms + latency_ms, 3)
        self.latencies_ms.append(round(latency_ms, 3))

    @property
    def completion_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.completed_tasks / self.total_tasks

    @property
    def runtime_failure_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.runtime_failure_count / self.total_tasks

    @property
    def policy_rejection_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.policy_rejection_count / self.total_tasks

    @property
    def recovery_success_rate(self) -> float:
        attempted_recoveries = self.recovered_tasks + self.failed_recovery_count
        if attempted_recoveries == 0:
            return 0.0
        return self.recovered_tasks / attempted_recoveries

    @property
    def average_latency_ms(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.total_latency_ms / self.total_tasks

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        index = max(0, ceil(len(ordered) * 0.95) - 1)
        return ordered[index]

    @property
    def average_route_score(self) -> float:
        if self.route_score_count == 0:
            return 0.0
        return self.route_score_total / self.route_score_count

    @property
    def average_health_score(self) -> float:
        if self.health_score_count == 0:
            return 0.0
        return self.health_score_total / self.health_score_count

    def to_dict(self) -> dict[str, object]:
        return {
            "system_name": self.system_name,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "generated_failure_tasks": self.generated_failure_tasks,
            "generated_policy_invalid_tasks": self.generated_policy_invalid_tasks,
            "generated_no_fallback_tasks": self.generated_no_fallback_tasks,
            "primary_execution_attempts": self.primary_execution_attempts,
            "primary_execution_failures": self.primary_execution_failures,
            "fallback_execution_attempts": self.fallback_execution_attempts,
            "fallback_execution_failures": self.fallback_execution_failures,
            "congestion_failure_count": self.congestion_failure_count,
            "runtime_failure_count": self.runtime_failure_count,
            "recovered_tasks": self.recovered_tasks,
            "failed_recovery_count": self.failed_recovery_count,
            "full_restart_count": self.full_restart_count,
            "reroute_count": self.reroute_count,
            "fallback_dispatch_count": self.fallback_dispatch_count,
            "quarantine_count": self.quarantine_count,
            "max_reroute_exhausted_count": self.max_reroute_exhausted_count,
            "policy_rejection_count": self.policy_rejection_count,
            "phi_cache_hits": self.phi_cache_hits,
            "phi_cache_updates": self.phi_cache_updates,
            "modulation_profiles_created": self.modulation_profiles_created,
            "arbitration_accepts": self.arbitration_accepts,
            "arbitration_rejects": self.arbitration_rejects,
            "arbitration_defers": self.arbitration_defers,
            "arbitration_reroutes": self.arbitration_reroutes,
            "snapshots_created": self.snapshots_created,
            "rollback_anchors_created": self.rollback_anchors_created,
            "replay_ledger_events": self.replay_ledger_events,
            "local_reentry_count": self.local_reentry_count,
            "health_score_updates": self.health_score_updates,
            "telemetry_events": self.telemetry_events,
            "recovery_policy_decisions": self.recovery_policy_decisions,
            "recovery_policy_reroutes": self.recovery_policy_reroutes,
            "recovery_policy_fallbacks": self.recovery_policy_fallbacks,
            "recovery_policy_failures": self.recovery_policy_failures,
            "virtual_patches_created": self.virtual_patches_created,
            "routes_evaluated": self.routes_evaluated,
            "dispatch_packets_created": self.dispatch_packets_created,
            "remap_attempts": self.remap_attempts,
            "remap_successes": self.remap_successes,
            "remap_failures": self.remap_failures,
            "route_score_total": round(self.route_score_total, 6),
            "route_score_count": self.route_score_count,
            "health_score_total": round(self.health_score_total, 6),
            "health_score_count": self.health_score_count,
            "quarantined_patch_count": self.quarantined_patch_count,
            "total_latency_ms": round(self.total_latency_ms, 3),
            "latencies_ms": list(self.latencies_ms),
            "completion_rate": round(self.completion_rate, 4),
            "runtime_failure_rate": round(self.runtime_failure_rate, 4),
            "policy_rejection_rate": round(self.policy_rejection_rate, 4),
            "recovery_success_rate": round(self.recovery_success_rate, 4),
            "average_latency_ms": round(self.average_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "average_route_score": round(self.average_route_score, 4),
            "average_health_score": round(self.average_health_score, 4),
        }
