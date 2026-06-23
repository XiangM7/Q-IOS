from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReplayLedgerEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    token_id: str
    event_type: str
    patch_id: str | None = None
    token_state: str | None = None
    message: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ReplayLedger:
    def __init__(self) -> None:
        self._events: list[ReplayLedgerEvent] = []

    def append(self, event: ReplayLedgerEvent) -> ReplayLedgerEvent:
        self._events.append(event)
        return event

    def append_event(
        self,
        task_id: str,
        token_id: str,
        event_type: str,
        patch_id: str | None = None,
        token_state: str | None = None,
        message: str = "",
        metadata: dict[str, object] | None = None,
    ) -> ReplayLedgerEvent:
        event = ReplayLedgerEvent(
            task_id=task_id,
            token_id=token_id,
            event_type=event_type,
            patch_id=patch_id,
            token_state=token_state,
            message=message,
            metadata=metadata or {},
        )
        return self.append(event)

    def get_events(self, task_id: str) -> list[ReplayLedgerEvent]:
        return [event for event in self._events if event.task_id == task_id]

    def get_token_events(self, token_id: str) -> list[ReplayLedgerEvent]:
        return [event for event in self._events if event.token_id == token_id]

    def get_last_successful_patch(self, token_id: str) -> str | None:
        for event in reversed(self.get_token_events(token_id)):
            if event.patch_id and event.event_type.endswith("completed"):
                return event.patch_id
        return None

    def get_failed_patches(self, token_id: str) -> set[str]:
        return {
            event.patch_id
            for event in self.get_token_events(token_id)
            if event.patch_id and "failed" in event.event_type
        }

    def get_replay_lineage(self, token_id: str) -> list[str]:
        return [
            f"{event.event_type}:{event.patch_id or '-'}"
            for event in self.get_token_events(token_id)
        ]
