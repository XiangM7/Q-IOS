from __future__ import annotations

import random

from pydantic import BaseModel, ConfigDict, PrivateAttr


class SimulationEnvironment(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    patch_count: int = 4
    failure_rate: float = 0.0
    congestion_rate: float = 0.0
    base_latency_ms: float = 20.0
    latency_jitter_ms: float = 5.0
    seed: int | None = None

    _rng: random.Random = PrivateAttr()

    def model_post_init(self, __context: object) -> None:
        self._rng = random.Random(self.seed)

    def sample_latency_ms(self) -> float:
        jitter = self._rng.uniform(-self.latency_jitter_ms, self.latency_jitter_ms)
        congestion_triggered = self._rng.random() < self.congestion_rate
        patch_factor = max(1.0, 4 / max(1, self.patch_count))
        congestion_factor = 1.0 + (self.congestion_rate if congestion_triggered else 0.0)
        latency = (self.base_latency_ms + jitter) * patch_factor * congestion_factor
        return round(max(0.0, latency), 3)

    def should_inject_failure(self) -> bool:
        return self._rng.random() < self.failure_rate

    def clone(self) -> "SimulationEnvironment":
        return SimulationEnvironment(**self.model_dump())
