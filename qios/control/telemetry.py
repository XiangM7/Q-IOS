from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    token_id: str
    patch_id: str
    route_id: str | None = None
    event_type: str
    latency_ms: float = 0.0
    success: bool
    failure_reason: str | None = None
    congestion_score: float = 0.0
    health_score: float = 1.0
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class TelemetryCollector:
    def __init__(self) -> None:
        self._events: list[TelemetryEvent] = []

    def record_event(
        self,
        *,
        task_id: str,
        token_id: str,
        patch_id: str,
        route_id: str | None,
        event_type: str,
        latency_ms: float,
        success: bool,
        failure_reason: str | None = None,
        congestion_score: float = 0.0,
        health_score: float = 1.0,
        metadata: dict[str, object] | None = None,
    ) -> TelemetryEvent:
        event = TelemetryEvent(
            task_id=task_id,
            token_id=token_id,
            patch_id=patch_id,
            route_id=route_id,
            event_type=event_type,
            latency_ms=round(latency_ms, 3),
            success=success,
            failure_reason=failure_reason,
            congestion_score=round(congestion_score, 3),
            health_score=round(health_score, 3),
            metadata=metadata or {},
        )
        self._events.append(event)
        return event

    def record_success(
        self,
        *,
        task_id: str,
        token_id: str,
        patch_id: str,
        route_id: str | None,
        latency_ms: float,
        congestion_score: float,
        health_score: float,
        metadata: dict[str, object] | None = None,
    ) -> TelemetryEvent:
        return self.record_event(
            task_id=task_id,
            token_id=token_id,
            patch_id=patch_id,
            route_id=route_id,
            event_type="execution_success",
            latency_ms=latency_ms,
            success=True,
            congestion_score=congestion_score,
            health_score=health_score,
            metadata=metadata,
        )

    def record_failure(
        self,
        *,
        task_id: str,
        token_id: str,
        patch_id: str,
        route_id: str | None,
        latency_ms: float,
        failure_reason: str,
        congestion_score: float,
        health_score: float,
        metadata: dict[str, object] | None = None,
    ) -> TelemetryEvent:
        return self.record_event(
            task_id=task_id,
            token_id=token_id,
            patch_id=patch_id,
            route_id=route_id,
            event_type="execution_failure",
            latency_ms=latency_ms,
            success=False,
            failure_reason=failure_reason,
            congestion_score=congestion_score,
            health_score=health_score,
            metadata=metadata,
        )

    def get_events(self) -> list[TelemetryEvent]:
        return list(self._events)

    def get_patch_events(self, patch_id: str) -> list[TelemetryEvent]:
        return [event for event in self._events if event.patch_id == patch_id]

    def get_recent_failure_count(self, patch_id: str) -> int:
        recent_events = self.get_patch_events(patch_id)[-10:]
        return sum(not event.success for event in recent_events)

    def get_average_latency(self, patch_id: str) -> float:
        events = self.get_patch_events(patch_id)
        if not events:
            return 0.0
        return round(sum(event.latency_ms for event in events) / len(events), 3)

    def get_recent_congestion(self, patch_id: str) -> float:
        events = self.get_patch_events(patch_id)[-5:]
        if not events:
            return 0.0
        return round(sum(event.congestion_score for event in events) / len(events), 3)
