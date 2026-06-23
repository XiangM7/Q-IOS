"""Simulation and benchmarking helpers for Q-IOS."""

from qios.sim.baselines import (
    DirectExecutionBaseline,
    QIOSSimulationSystem,
    RetryOnlyBaseline,
    StaticRoutingBaseline,
)
from qios.sim.environment import SimulationEnvironment
from qios.sim.metrics import SimulationMetrics
from qios.sim.workload import WorkloadGenerator

__all__ = [
    "DirectExecutionBaseline",
    "QIOSSimulationSystem",
    "SimulationRunResult",
    "RetryOnlyBaseline",
    "SimulationEnvironment",
    "SimulationMetrics",
    "StaticRoutingBaseline",
    "WorkloadGenerator",
    "run_simulation",
]


def __getattr__(name: str):
    if name in {"SimulationRunResult", "run_simulation"}:
        from qios.sim.runner import SimulationRunResult, run_simulation

        exports = {
            "SimulationRunResult": SimulationRunResult,
            "run_simulation": run_simulation,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
