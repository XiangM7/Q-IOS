from __future__ import annotations

import random

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from qios.models import PatchType, TaskRequest


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
        quarantine_penalty = 0.45 if self.quarantined else 0.0
        return self.health_score - self.congestion_score - quarantine_penalty


class SimulationEnvironment(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    patch_count: int = 4
    failure_rate: float = 0.0
    fallback_failure_rate: float = 0.0
    congestion_rate: float = 0.0
    base_latency_ms: float = 20.0
    latency_jitter_ms: float = 5.0
    quarantine_threshold: int = 3
    seed: int | None = None
    patches: dict[str, PatchHealth] = Field(default_factory=dict)

    _rng: random.Random = PrivateAttr()

    def model_post_init(self, __context: object) -> None:
        self._rng = random.Random(self.seed)
        if not self.patches:
            self.patches = self._initialize_patches()

    def sample_latency_ms(self, patch_id: str | None = None) -> float:
        if patch_id is None:
            jitter = self._rng.uniform(-self.latency_jitter_ms, self.latency_jitter_ms)
            congestion_triggered = self._rng.random() < self.congestion_rate
            congestion_factor = 1.0 + (self.congestion_rate if congestion_triggered else 0.0)
            latency = (self.base_latency_ms + jitter) * congestion_factor
            return round(max(0.0, latency), 3)

        patch = self.patches[patch_id]
        self._refresh_congestion(patch)
        jitter = self._rng.uniform(-self.latency_jitter_ms, self.latency_jitter_ms)
        latency_multiplier = 1.0 + patch.congestion_score + (1.0 - patch.health_score) * 0.2
        if patch.quarantined:
            latency_multiplier += 0.15
        latency = (self.base_latency_ms + jitter) * latency_multiplier
        return round(max(0.0, latency), 3)

    def should_inject_failure(self) -> bool:
        return self._rng.random() < self.failure_rate

    def failure_probability(
        self,
        task: TaskRequest,
        patch_id: str,
        *,
        is_fallback: bool = False,
    ) -> float:
        patch = self.patches[patch_id]
        objective = task.objective.lower()

        if "fail" in objective:
            objective_risk = 0.08 if is_fallback else 0.72
        else:
            objective_risk = 0.03

        fallback_risk = self.fallback_failure_rate if is_fallback else 0.0
        health_risk = (1.0 - patch.health_score) * (0.32 if is_fallback else 0.6)
        congestion_risk = patch.congestion_score * (0.22 if is_fallback else 0.4)
        quarantine_risk = 0.08 if is_fallback else 0.2
        if not patch.quarantined:
            quarantine_risk = 0.0
        constraint_risk = 0.1 if task.constraints.get("sandbox_required") and patch.patch_type == PatchType.HUMAN_REVIEW.value else 0.0

        return min(
            0.98,
            max(
                0.01,
                objective_risk + fallback_risk + health_risk + congestion_risk + quarantine_risk + constraint_risk,
            ),
        )

    def register_patch_outcome(self, patch_id: str, *, success: bool) -> bool:
        patch = self.patches[patch_id]
        just_quarantined = False

        if success:
            patch.success_count += 1
            patch.health_score = round(min(1.0, patch.health_score + 0.05), 3)
            patch.congestion_score = round(max(0.0, patch.congestion_score - 0.06), 3)
            if patch.quarantined and patch.health_score >= 0.8 and patch.success_count > patch.failure_count:
                patch.quarantined = False
        else:
            patch.failure_count += 1
            patch.health_score = round(max(0.0, patch.health_score - (0.16 + patch.congestion_score * 0.12)), 3)
            patch.congestion_score = round(min(1.0, patch.congestion_score + 0.14 + self.congestion_rate * 0.24), 3)
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
                health_score=round(0.78 + self._rng.random() * 0.18, 3),
                congestion_score=round(min(1.0, max(0.0, self.congestion_rate * 0.5 + self._rng.random() * 0.1)), 3),
            )

        return patches

    def _refresh_congestion(self, patch: PatchHealth) -> None:
        delta = self._rng.uniform(-0.08, 0.12)
        blended = patch.congestion_score * 0.6 + self.congestion_rate * 0.4 + delta
        patch.congestion_score = round(min(1.0, max(0.0, blended)), 3)
