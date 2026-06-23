from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DispatchPacket(BaseModel):
    dispatch_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    token_id: str
    virtual_patch_id: str
    physical_patch_id: str
    route_id: str
    role: str
    authorization_tags: list[str] = Field(default_factory=list)
    isolation_domain: str
    phi_modulation: float
    route_score: float
    lifecycle_state: str
    fallback_patch_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class DispatchPacketBuilder:
    def build(
        self,
        token,
        virtual_patch,
        route_candidate,
        authorization_tags: list[str] | None = None,
        fallback_patch_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> DispatchPacket:
        return DispatchPacket(
            task_id=token.task_id,
            token_id=token.token_id,
            virtual_patch_id=virtual_patch.virtual_patch_id,
            physical_patch_id=route_candidate.physical_patch_id,
            route_id=route_candidate.route_id,
            role=token.role,
            authorization_tags=list(authorization_tags or ["phi-token", "policy-admitted"]),
            isolation_domain=virtual_patch.isolation_domain,
            phi_modulation=token.phi_modulation,
            route_score=route_candidate.final_score,
            lifecycle_state=token.lifecycle_state.value,
            fallback_patch_id=fallback_patch_id,
            metadata=metadata or {},
        )
