from __future__ import annotations

from pydantic import BaseModel, Field


class RemapResult(BaseModel):
    old_physical_patch_id: str
    new_physical_patch_id: str | None = None
    virtual_patch_id: str
    route_id: str | None = None
    reason: str
    preserved_virtual_address: bool
    success: bool
    metadata: dict[str, object] = Field(default_factory=dict)


class Remapper:
    def __init__(self, virtual_patch_manager=None) -> None:
        self.virtual_patch_manager = virtual_patch_manager

    def remap(
        self,
        virtual_patch_id,
        failed_physical_patch_id,
        candidate_patch_ids,
        health_manager,
        route_evaluator,
        patch_registry,
    ) -> RemapResult:
        if self.virtual_patch_manager is None:
            return RemapResult(
                old_physical_patch_id=failed_physical_patch_id,
                virtual_patch_id=virtual_patch_id,
                reason="Virtual patch manager unavailable.",
                preserved_virtual_address=False,
                success=False,
            )

        virtual_patch = self.virtual_patch_manager.get_virtual_patch(virtual_patch_id)
        if virtual_patch is None:
            return RemapResult(
                old_physical_patch_id=failed_physical_patch_id,
                virtual_patch_id=virtual_patch_id,
                reason="Virtual patch not found.",
                preserved_virtual_address=False,
                success=False,
            )

        candidate_patches = []
        for patch_id in candidate_patch_ids:
            patch = patch_registry.get_patch(patch_id)
            if patch is None or patch.patch_id == failed_physical_patch_id:
                continue
            candidate_patches.append(patch)

        if not candidate_patches:
            return RemapResult(
                old_physical_patch_id=failed_physical_patch_id,
                virtual_patch_id=virtual_patch_id,
                reason="No candidate physical patches available for remap.",
                preserved_virtual_address=True,
                success=False,
            )

        routes = route_evaluator.evaluate_routes(
            virtual_patch=virtual_patch,
            candidate_patches=candidate_patches,
            health_manager=health_manager,
            patch_registry=patch_registry,
        )
        best_route = None
        for route in routes:
            patch = patch_registry.get_patch(route.physical_patch_id)
            if patch is not None and not patch.quarantined:
                best_route = route
                break
        if best_route is None and routes:
            best_route = routes[0]

        if best_route is None:
            return RemapResult(
                old_physical_patch_id=failed_physical_patch_id,
                virtual_patch_id=virtual_patch_id,
                reason="No survivable route remained after evaluation.",
                preserved_virtual_address=True,
                success=False,
                metadata={"evaluated_routes": len(routes)},
            )

        self.virtual_patch_manager.preserve_virtual_address_on_remap(
            virtual_patch_id,
            best_route.physical_patch_id,
        )
        return RemapResult(
            old_physical_patch_id=failed_physical_patch_id,
            new_physical_patch_id=best_route.physical_patch_id,
            virtual_patch_id=virtual_patch_id,
            route_id=best_route.route_id,
            reason="Selected highest-scoring survivable remap candidate.",
            preserved_virtual_address=True,
            success=True,
            metadata={
                "evaluated_routes": len(routes),
                "route_score": best_route.final_score,
            },
        )
