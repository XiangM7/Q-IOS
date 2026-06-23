from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SnapshotPackage(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    token_id: str
    patch_id: str
    token_state: str
    phi_modulation: float
    rollback_anchor_id: str | None = None
    replay_lineage: list[str] = Field(default_factory=list)
    memory_isolation_label: str = "default"
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SnapshotPackageBuilder:
    def build(
        self,
        token,
        patch_id: str,
        rollback_anchor_id: str | None = None,
        replay_lineage: list[str] | None = None,
        memory_isolation_label: str = "default",
        metadata: dict[str, object] | None = None,
    ) -> SnapshotPackage:
        return SnapshotPackage(
            task_id=token.task_id,
            token_id=token.token_id,
            patch_id=patch_id,
            token_state=token.lifecycle_state.value,
            phi_modulation=token.phi_modulation,
            rollback_anchor_id=rollback_anchor_id,
            replay_lineage=replay_lineage or [],
            memory_isolation_label=memory_isolation_label,
            metadata=metadata or {},
        )
