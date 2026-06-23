from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PhiCacheEntry(BaseModel):
    patch_id: str
    role: str
    success_count: int = 0
    failure_count: int = 0
    reroute_count: int = 0
    total_latency_ms: float = 0.0
    average_latency_ms: float = 0.0
    last_health_score: float | None = None
    preference_score: float = 0.5
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def has_history(self) -> bool:
        return (self.success_count + self.failure_count + self.reroute_count) > 0


class PhiCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], PhiCacheEntry] = {}

    def get_entry(self, patch_id: str, role: str) -> PhiCacheEntry:
        key = (patch_id, role)
        if key not in self._entries:
            self._entries[key] = PhiCacheEntry(patch_id=patch_id, role=role)
        return self._entries[key]

    def update_success(
        self,
        patch_id: str,
        role: str,
        latency_ms: float,
        health_score: float | None = None,
    ) -> PhiCacheEntry:
        entry = self.get_entry(patch_id, role)
        entry.success_count += 1
        entry.total_latency_ms = round(entry.total_latency_ms + latency_ms, 3)
        entry.average_latency_ms = round(
            entry.total_latency_ms / max(1, entry.success_count + entry.failure_count),
            3,
        )
        entry.last_health_score = health_score if health_score is not None else entry.last_health_score
        self._recompute_preference(entry)
        return entry

    def update_failure(
        self,
        patch_id: str,
        role: str,
        latency_ms: float = 0.0,
        health_score: float | None = None,
    ) -> PhiCacheEntry:
        entry = self.get_entry(patch_id, role)
        entry.failure_count += 1
        entry.total_latency_ms = round(entry.total_latency_ms + latency_ms, 3)
        entry.average_latency_ms = round(
            entry.total_latency_ms / max(1, entry.success_count + entry.failure_count),
            3,
        )
        entry.last_health_score = health_score if health_score is not None else entry.last_health_score
        self._recompute_preference(entry)
        return entry

    def update_reroute(self, patch_id: str, role: str) -> PhiCacheEntry:
        entry = self.get_entry(patch_id, role)
        entry.reroute_count += 1
        self._recompute_preference(entry)
        return entry

    def get_preference_score(self, patch_id: str, role: str) -> float:
        return self.get_entry(patch_id, role).preference_score

    def rank_patches(self, patch_ids: list[str], role: str) -> list[tuple[str, float]]:
        ranked = [(patch_id, self.get_preference_score(patch_id, role)) for patch_id in patch_ids]
        return sorted(ranked, key=lambda item: (-item[1], item[0]))

    def _recompute_preference(self, entry: PhiCacheEntry) -> None:
        score = 0.5
        score += min(0.28, entry.success_count * 0.05)
        score -= min(0.35, entry.failure_count * 0.09)
        score -= min(0.12, entry.reroute_count * 0.03)
        score -= min(0.18, entry.average_latency_ms / 600.0)

        if entry.last_health_score is not None:
            score += (entry.last_health_score - 0.5) * 0.2

        entry.preference_score = round(min(1.0, max(0.0, score)), 3)
        entry.updated_at = utc_now()
