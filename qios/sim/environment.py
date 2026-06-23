from __future__ import annotations

import random

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from qios.models import PatchType


class PatchHealth(BaseModel):
    patch_id: str
    patch_type: str
    health_score: float
    failure_count: int = 0
    success_count: int = 0
    congestion_score: float = 0.0
    quarantined: bool = False

    @property
    def routing_score(self) -> float:
        quarantine_penalty = 0.2 if self.quarantined else 0.0
        return self.health_score - (self.congestion_score * 0.6) - quarantine_penalty


class SimulationEnvironment(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    patch_count: int = 4
    failure_rate: float = 0.0
    fallback_failure_rate: float = 0.0
    congestion_rate: float = 0.0
    base_latency_ms: float = 20.0
    latency_jitter_ms: float = 5.0
    quarantine_threshold: int = 6
    seed: int | None = None
    patches: dict[str, PatchHealth] = Field(default_factory=dict)

    _rng: random.Random = PrivateAttr()

    def model_post_init(self, __context: object) -> None:
        self._rng = random.Random(self.seed)
        if not self.patches:
            self.patches = self._initialize_patches()

    def prepare_attempt(self, patch_id: str) -> tuple[float, bool]:
        patch = self.patches[patch_id]
        self._refresh_congestion(patch)
        congestion_event = self._rng.random() < min(
            0.95, self.congestion_rate * (0.5 + patch.congestion_score * 0.5)
        )
        latency_ms = self.sample_latency_ms(patch_id)
        if congestion_event:
            latency_ms = round(latency_ms * 1.12, 3)
        return latency_ms, congestion_event

    def sample_latency_ms(self, patch_id: str | None = None) -> float:
        if patch_id is None:
            jitter = self._rng.uniform(-self.latency_jitter_ms, self.latency_jitter_ms)
            congestion_triggered = self._rng.random() < self.congestion_rate
            congestion_factor = 1.0 + (self.congestion_rate * 0.4 if congestion_triggered else 0.0)
            latency = (self.base_latency_ms + jitter) * congestion_factor
            return round(max(0.0, latency), 3)

        patch = self.patches[patch_id]
        jitter = self._rng.uniform(-self.latency_jitter_ms, self.latency_jitter_ms)
        latency_multiplier = 1.0 + (patch.congestion_score * 1.4) + ((1.0 - patch.health_score) * 0.12)
        if patch.quarantined:
            latency_multiplier += 0.08
        latency = (self.base_latency_ms + jitter) * latency_multiplier
        return round(max(0.0, latency), 3)

    def sample_fallback_failure(self) -> bool:
        return self._rng.random() < self.fallback_failure_rate

    def sample_congestion_failure(self, patch_id: str, congestion_event: bool) -> bool:
        if not congestion_event:
            return False
        patch = self.patches[patch_id]
        chance = min(0.12, 0.01 + (patch.congestion_score * 0.05) + (self.congestion_rate * 0.03))
        return self._rng.random() < chance

    def sample_patch_degradation_failure(self, patch_id: str) -> bool:
        patch = self.patches[patch_id]
        chance = 0.0
        if patch.health_score < 0.55:
            chance += (0.55 - patch.health_score) * 0.08
        if patch.quarantined:
            chance += 0.03
        return self._rng.random() < min(0.12, chance)

    def register_patch_outcome(self, patch_id: str, *, success: bool) -> bool:
        patch = self.patches[patch_id]
        just_quarantined = False

        if success:
            patch.success_count += 1
            patch.health_score = round(min(1.0, patch.health_score + 0.02), 3)
            patch.congestion_score = round(max(0.0, patch.congestion_score - 0.03), 3)
            if patch.quarantined and patch.health_score >= 0.72 and patch.success_count > patch.failure_count:
                patch.quarantined = False
        else:
            patch.failure_count += 1
            patch.health_score = round(max(0.0, patch.health_score - 0.045), 3)
            patch.congestion_score = round(min(1.0, patch.congestion_score + 0.05 + self.congestion_rate * 0.1), 3)
            if not patch.quarantined and patch.failure_count >= self.quarantine_threshold:
                patch.quarantined = True
                just_quarantined = True

        return just_quarantined

    def select_best_patch(
        self,
        *,
        preferred_types: list[str] | None = None,
        exclude_ids: set[str] | None = None,
        include_quarantined: bool = False,
        allow_fallback: bool = True,
    ) -> PatchHealth | None:
        excluded = exclude_ids or set()
        candidates: list[PatchHealth] = []

        for patch in self.patches.values():
            if patch.patch_id in excluded:
                continue
            if not include_quarantined and patch.quarantined:
                continue
            if preferred_types is not None and patch.patch_type not in preferred_types:
                continue
            if not allow_fallback and patch.patch_type == PatchType.FALLBACK.value:
                continue
            candidates.append(patch)

        if not candidates:
            return None

        ordered = sorted(
            candidates,
            key=lambda patch: (patch.routing_score, patch.health_score, -patch.congestion_score, patch.patch_id),
            reverse=True,
        )
        return ordered[0]

    def baseline_patch_ids(self) -> list[str]:
        patch_ids = [
            patch.patch_id
            for patch in self.patches.values()
            if patch.patch_type != PatchType.FALLBACK.value
        ]
        return sorted(patch_ids) or sorted(self.patches)

    def clone(self) -> "SimulationEnvironment":
        return SimulationEnvironment(**self.model_dump())

    def _initialize_patches(self) -> dict[str, PatchHealth]:
        patch_types = [
            PatchType.SANDBOX.value,
            PatchType.ANALYSIS.value,
            PatchType.FALLBACK.value,
            PatchType.HUMAN_REVIEW.value,
        ]
        patches: dict[str, PatchHealth] = {}

        for index in range(self.patch_count):
            patch_type = patch_types[index % len(patch_types)]
            patch_id = f"{patch_type}_{index}"
            patches[patch_id] = PatchHealth(
                patch_id=patch_id,
                patch_type=patch_type,
                health_score=round(0.82 + self._rng.random() * 0.14, 3),
                congestion_score=round(
                    min(1.0, max(0.0, self.congestion_rate * 0.35 + self._rng.random() * 0.06)),
                    3,
                ),
            )

        return patches

    def _refresh_congestion(self, patch: PatchHealth) -> None:
        delta = self._rng.uniform(-0.03, 0.04)
        blended = (patch.congestion_score * 0.75) + (self.congestion_rate * 0.25) + delta
        patch.congestion_score = round(min(1.0, max(0.0, blended)), 3)
