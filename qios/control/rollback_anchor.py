from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RollbackAnchor(BaseModel):
    anchor_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    token_id: str
    patch_id: str
    anchor_type: str
    token_state: str | None = None
    replay_position: int | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RollbackAnchorManager:
    def __init__(self) -> None:
        self._anchors: list[RollbackAnchor] = []

    def create_anchor(
        self,
        task_id: str,
        token_id: str,
        patch_id: str,
        anchor_type: str,
        token_state: str | None = None,
        replay_position: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> RollbackAnchor:
        anchor = RollbackAnchor(
            task_id=task_id,
            token_id=token_id,
            patch_id=patch_id,
            anchor_type=anchor_type,
            token_state=token_state,
            replay_position=replay_position,
            metadata=metadata or {},
        )
        self._anchors.append(anchor)
        return anchor

    def get_anchor(self, anchor_id: str) -> RollbackAnchor | None:
        for anchor in self._anchors:
            if anchor.anchor_id == anchor_id:
                return anchor
        return None

    def get_latest_anchor(self, token_id: str) -> RollbackAnchor | None:
        for anchor in reversed(self._anchors):
            if anchor.token_id == token_id:
                return anchor
        return None

    def list_anchors(self, token_id: str) -> list[RollbackAnchor]:
        return [anchor for anchor in self._anchors if anchor.token_id == token_id]
