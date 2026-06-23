from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VirtualPatchAddress(BaseModel):
    virtual_patch_id: str = Field(default_factory=lambda: str(uuid4()))
    logic_id: str
    role: str
    isolation_domain: str = "default"
    preferred_patch_type: str
    allowed_physical_patch_ids: list[str] = Field(default_factory=list)
    lifecycle_state: str = "ACTIVE"
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class VirtualPatchAddressManager:
    def __init__(self) -> None:
        self._addresses: dict[str, VirtualPatchAddress] = {}

    def create_virtual_patch(
        self,
        logic_id: str,
        role: str,
        preferred_patch_type: str,
        allowed_physical_patch_ids: list[str] | None = None,
        isolation_domain: str = "default",
        metadata: dict[str, object] | None = None,
    ) -> VirtualPatchAddress:
        address = VirtualPatchAddress(
            logic_id=logic_id,
            role=role,
            preferred_patch_type=preferred_patch_type,
            allowed_physical_patch_ids=list(allowed_physical_patch_ids or []),
            isolation_domain=isolation_domain,
            metadata=metadata or {},
        )
        self._addresses[address.virtual_patch_id] = address
        return address

    def get_virtual_patch(self, virtual_patch_id: str) -> VirtualPatchAddress | None:
        return self._addresses.get(virtual_patch_id)

    def resolve_allowed_physical_patches(self, virtual_patch_id: str) -> list[str]:
        address = self.get_virtual_patch(virtual_patch_id)
        if address is None:
            return []
        return list(address.allowed_physical_patch_ids)

    def preserve_virtual_address_on_remap(
        self,
        old_virtual_patch_id: str,
        new_physical_patch_id: str,
    ) -> VirtualPatchAddress | None:
        address = self.get_virtual_patch(old_virtual_patch_id)
        if address is None:
            return None
        address.metadata["current_physical_patch_id"] = new_physical_patch_id
        history = list(address.metadata.get("physical_patch_history", []))
        history.append(new_physical_patch_id)
        address.metadata["physical_patch_history"] = history
        if new_physical_patch_id not in address.allowed_physical_patch_ids:
            address.allowed_physical_patch_ids.append(new_physical_patch_id)
        address.lifecycle_state = "REMAPPED"
        return address
