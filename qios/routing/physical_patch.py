from __future__ import annotations

from pydantic import BaseModel, Field

from qios.models import PatchType


class PhysicalPatch(BaseModel):
    patch_id: str
    patch_type: str
    domain: str = "default"
    supported_roles: list[str] = Field(default_factory=list)
    isolation_domain: str = "default"
    capacity: int = 8
    current_load: int = 0
    health_score: float = 0.95
    congestion_score: float = 0.0
    quarantined: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class PhysicalPatchRegistry:
    def __init__(self, seed_defaults: bool = False) -> None:
        self._patches: dict[str, PhysicalPatch] = {}
        if seed_defaults:
            self._seed_default_patches()

    def register_patch(self, patch: PhysicalPatch) -> PhysicalPatch:
        self._patches[patch.patch_id] = patch
        return patch

    def get_patch(self, patch_id: str) -> PhysicalPatch | None:
        return self._patches.get(patch_id)

    def list_patches(self) -> list[PhysicalPatch]:
        return list(self._patches.values())

    def list_candidate_patches(
        self,
        role: str | None = None,
        patch_type: str | None = None,
        isolation_domain: str | None = None,
        exclude_quarantined: bool = True,
    ) -> list[PhysicalPatch]:
        candidates: list[PhysicalPatch] = []
        for patch in self._patches.values():
            if role is not None and patch.supported_roles and role not in patch.supported_roles:
                continue
            if patch_type is not None and patch.patch_type != patch_type:
                continue
            if isolation_domain is not None and patch.isolation_domain != isolation_domain:
                continue
            if exclude_quarantined and patch.quarantined:
                continue
            candidates.append(patch)
        return candidates

    def update_load(self, patch_id: str, delta: int) -> PhysicalPatch | None:
        patch = self.get_patch(patch_id)
        if patch is None:
            return None
        patch.current_load = max(0, patch.current_load + delta)
        return patch

    def mark_quarantined(self, patch_id: str) -> PhysicalPatch | None:
        patch = self.get_patch(patch_id)
        if patch is None:
            return None
        patch.quarantined = True
        return patch

    def update_health(self, patch_id: str, health_score: float) -> PhysicalPatch | None:
        patch = self.get_patch(patch_id)
        if patch is None:
            return None
        patch.health_score = round(min(1.0, max(0.0, health_score)), 3)
        return patch

    def update_congestion(self, patch_id: str, congestion_score: float) -> PhysicalPatch | None:
        patch = self.get_patch(patch_id)
        if patch is None:
            return None
        patch.congestion_score = round(min(1.0, max(0.0, congestion_score)), 3)
        return patch

    def _seed_default_patches(self) -> None:
        defaults = [
            PhysicalPatch(
                patch_id=PatchType.ANALYSIS.value,
                patch_type=PatchType.ANALYSIS.value,
                domain="analysis",
                supported_roles=["analysis", "default_execution"],
            ),
            PhysicalPatch(
                patch_id=PatchType.SANDBOX.value,
                patch_type=PatchType.SANDBOX.value,
                domain="sandbox",
                supported_roles=["execution", "default_execution"],
            ),
            PhysicalPatch(
                patch_id=PatchType.FALLBACK.value,
                patch_type=PatchType.FALLBACK.value,
                domain="fallback",
                supported_roles=["analysis", "execution", "default_execution"],
            ),
            PhysicalPatch(
                patch_id="static_patch",
                patch_type="static_patch",
                domain="static",
                supported_roles=["analysis", "execution", "default_execution"],
            ),
        ]
        for patch in defaults:
            self.register_patch(patch)
