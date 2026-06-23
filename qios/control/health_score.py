from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HealthScore(BaseModel):
    patch_id: str
    health_score: float = Field(default=0.98, ge=0.0, le=1.0)
    success_count: int = 0
    failure_count: int = 0
    quarantine_count: int = 0
    average_latency_ms: float = 0.0
    congestion_score: float = Field(default=0.0, ge=0.0, le=1.0)
    last_failure_reason: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class HealthScoreManager:
    def __init__(self) -> None:
        self._scores: dict[str, HealthScore] = {}
        self._quarantined: set[str] = set()

    def get_score(self, patch_id: str) -> HealthScore:
        if patch_id not in self._scores:
            self._scores[patch_id] = HealthScore(patch_id=patch_id)
        return self._scores[patch_id]

    def record_success(self, patch_id: str, latency_ms: float) -> HealthScore:
        score = self.get_score(patch_id)
        score.success_count += 1
        score.average_latency_ms = self._merge_average(
            score.average_latency_ms,
            score.success_count + score.failure_count - 1,
            latency_ms,
        )
        score.last_failure_reason = None
        score.health_score = self._clamp(
            score.health_score
            + 0.02
            - min(0.01, latency_ms / 5000.0)
            - min(0.04, score.congestion_score * 0.03)
        )
        score.updated_at = utc_now()
        if score.health_score >= 0.55 and patch_id in self._quarantined:
            self._quarantined.remove(patch_id)
        return score

    def record_failure(
        self,
        patch_id: str,
        latency_ms: float = 0.0,
        reason: str = "",
    ) -> HealthScore:
        score = self.get_score(patch_id)
        score.failure_count += 1
        score.average_latency_ms = self._merge_average(
            score.average_latency_ms,
            score.success_count + score.failure_count - 1,
            latency_ms,
        )
        score.last_failure_reason = reason or None
        score.health_score = self._clamp(
            score.health_score
            - 0.1
            - min(0.03, latency_ms / 2500.0)
            - min(0.05, score.congestion_score * 0.06)
        )
        score.updated_at = utc_now()
        return score

    def record_congestion(self, patch_id: str, congestion_score: float) -> HealthScore:
        score = self.get_score(patch_id)
        score.congestion_score = self._clamp(congestion_score)
        score.health_score = self._clamp(score.health_score - min(0.06, score.congestion_score * 0.08))
        score.updated_at = utc_now()
        return score

    def should_quarantine(self, patch_id: str) -> bool:
        score = self.get_score(patch_id)
        return (
            score.failure_count >= 3
            or score.health_score <= 0.3
            or (score.failure_count >= 2 and score.congestion_score >= 0.85)
        )

    def quarantine(self, patch_id: str) -> HealthScore:
        score = self.get_score(patch_id)
        score.quarantine_count += 1
        score.health_score = self._clamp(score.health_score - 0.08)
        score.updated_at = utc_now()
        self._quarantined.add(patch_id)
        return score

    def is_quarantined(self, patch_id: str) -> bool:
        return patch_id in self._quarantined

    def rank_by_health(self, patch_ids: list[str]) -> list[tuple[str, float]]:
        ranked = [(patch_id, self.get_score(patch_id).health_score) for patch_id in patch_ids]
        return sorted(ranked, key=lambda item: (-item[1], item[0]))

    def _merge_average(self, current_average: float, current_count: int, new_value: float) -> float:
        if current_count <= 0:
            return round(new_value, 3)
        return round(((current_average * current_count) + new_value) / (current_count + 1), 3)

    def _clamp(self, value: float) -> float:
        return round(min(1.0, max(0.0, value)), 3)
