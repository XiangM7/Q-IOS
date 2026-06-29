
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TokenState(str, Enum):
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RECONFIGURING = "RECONFIGURING"
    REASSIGNED = "REASSIGNED"
    TERMINATED = "TERMINATED"


class PatchType(str, Enum):
    SANDBOX = "sandbox_patch"
    ANALYSIS = "analysis_patch"
    FALLBACK = "fallback_patch"
    HUMAN_REVIEW = "human_review_patch"


class TaskRequest(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    objective: str
    priority: int = 5
    entities: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    output_condition: str = "complete successfully"
    fallback: str | None = None


class StructuredJobModel(BaseModel):
    task_id: str
    objective: str
    entities: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    output_condition: str
    priority: int
    fallback: str | None = None

# 定义 PhiToken
class PhiToken(BaseModel):
    token_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    role: str
    priority: int
    patch_hint: str | None = None
    assigned_patch: str | None = None
    fallback: str | None = None
    lifecycle_state: TokenState = TokenState.PLANNED
    phi_modulation: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    task_id: str
    token_id: str
    status: TokenState
    success: bool
    patch: str | None = None
    output: str | None = None
    failure_reason: str | None = None
    executed_at: datetime = Field(default_factory=utc_now)


class ExecutionEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    token_id: str
    event_type: str
    state: TokenState
    message: str
    patch: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SnapshotPackage(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    token_id: str
    lifecycle_state: TokenState
    assigned_patch: str | None = None
    phi_modulation: float
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class PipelineOutcome(BaseModel):
    task_id: str
    token_id: str
    success: bool
    final_state: TokenState
    final_patch: str | None = None
    recovery_performed: bool = False
    failure_reason: str | None = None
    control_metrics: dict[str, int] = Field(default_factory=dict)
    control_metadata: dict[str, Any] = Field(default_factory=dict)
