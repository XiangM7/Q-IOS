from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil


@dataclass
class SimulationMetrics:
    system_name: str
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    recovered_tasks: int = 0
    full_restart_count: int = 0
    reroute_count: int = 0
    policy_rejection_count: int = 0
    total_latency_ms: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)

    def record_task(
        self,
        *,
        latency_ms: float,
        completed: bool,
        recovered: bool = False,
        full_restarts: int = 0,
        reroutes: int = 0,
        policy_rejected: bool = False,
    ) -> None:
        self.total_tasks += 1
        if completed:
            self.completed_tasks += 1
        else:
            self.failed_tasks += 1
        if recovered:
            self.recovered_tasks += 1
        self.full_restart_count += full_restarts
        self.reroute_count += reroutes
        if policy_rejected:
            self.policy_rejection_count += 1
        self.total_latency_ms = round(self.total_latency_ms + latency_ms, 3)
        self.latencies_ms.append(round(latency_ms, 3))

    @property
    def completion_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.completed_tasks / self.total_tasks

    @property
    def recovery_success_rate(self) -> float:
        recovery_events = self.recovered_tasks + self.failed_tasks
        if recovery_events == 0:
            return 0.0
        return self.recovered_tasks / recovery_events

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

    def to_dict(self) -> dict[str, object]:
        return {
            "system_name": self.system_name,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "recovered_tasks": self.recovered_tasks,
            "full_restart_count": self.full_restart_count,
            "reroute_count": self.reroute_count,
            "policy_rejection_count": self.policy_rejection_count,
            "total_latency_ms": round(self.total_latency_ms, 3),
            "latencies_ms": list(self.latencies_ms),
            "completion_rate": round(self.completion_rate, 4),
            "recovery_success_rate": round(self.recovery_success_rate, 4),
            "average_latency_ms": round(self.average_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
        }
