from __future__ import annotations

from pydantic import BaseModel


class RouteCandidate(BaseModel):
    route_id: str
    virtual_patch_id: str
    physical_patch_id: str
    survivability_score: float
    fidelity_score: float
    latency_score: float
    congestion_score: float
    health_score: float
    isolation_compatible: bool
    failover_available: bool
    final_score: float
    reason: str


class RouteEvaluator:
    def evaluate_routes(
        self,
        virtual_patch,
        candidate_patches,
        health_manager,
        patch_registry,
        phi_cache=None,
        congestion_map=None,
    ) -> list[RouteCandidate]:
        viable_patch_count = sum(not patch.quarantined for patch in candidate_patches)
        routes: list[RouteCandidate] = []

        for patch in candidate_patches:
            score = health_manager.get_score(patch.patch_id)
            health_score = round((score.health_score + patch.health_score) / 2.0, 3)
            congestion_score = round(
                (congestion_map or {}).get(patch.patch_id, patch.congestion_score),
                3,
            )
            average_latency_ms = score.average_latency_ms
            latency_score = self._clamp(1.0 - min(0.7, average_latency_ms / 200.0))
            isolation_compatible = (
                virtual_patch.isolation_domain == patch.isolation_domain
                or virtual_patch.isolation_domain == "default"
            )
            fidelity_score = self._fidelity_score(virtual_patch, patch)
            failover_available = viable_patch_count > 1
            survivability_score = self._clamp(
                (health_score * 0.6)
                + ((1.0 - congestion_score) * 0.25)
                + (0.15 if not patch.quarantined else 0.0)
                + (0.05 if failover_available else 0.0)
            )
            phi_cache_score = 0.0
            if phi_cache is not None:
                phi_cache_score = phi_cache.get_preference_score(patch.patch_id, virtual_patch.role)
            load_penalty = 0.0
            if patch.capacity > 0:
                load_penalty = min(0.15, patch.current_load / patch.capacity * 0.15)

            final_score = (
                (health_score * 0.32)
                + (fidelity_score * 0.22)
                + (latency_score * 0.12)
                + (survivability_score * 0.22)
                + ((1.0 - congestion_score) * 0.08)
                + (phi_cache_score * 0.04)
                - load_penalty
            )
            if patch.quarantined:
                final_score -= 0.28
            if not isolation_compatible:
                final_score -= 0.45

            final_score = self._clamp(final_score)
            route = RouteCandidate(
                route_id=f"route:{virtual_patch.virtual_patch_id}:{patch.patch_id}",
                virtual_patch_id=virtual_patch.virtual_patch_id,
                physical_patch_id=patch.patch_id,
                survivability_score=round(survivability_score, 3),
                fidelity_score=round(fidelity_score, 3),
                latency_score=round(latency_score, 3),
                congestion_score=round(congestion_score, 3),
                health_score=round(health_score, 3),
                isolation_compatible=isolation_compatible,
                failover_available=failover_available,
                final_score=round(final_score, 3),
                reason=(
                    f"health={health_score:.2f}, fidelity={fidelity_score:.2f}, "
                    f"latency={latency_score:.2f}, congestion={congestion_score:.2f}, "
                    f"isolation={'ok' if isolation_compatible else 'mismatch'}, "
                    f"quarantined={patch.quarantined}"
                ),
            )
            routes.append(route)

        return sorted(routes, key=lambda item: (-item.final_score, item.physical_patch_id))

    def _fidelity_score(self, virtual_patch, patch) -> float:
        if patch.patch_id in virtual_patch.allowed_physical_patch_ids:
            allowed_bonus = 0.08
        else:
            allowed_bonus = 0.0
        if patch.patch_type == virtual_patch.preferred_patch_type:
            return self._clamp(0.92 + allowed_bonus)
        if virtual_patch.role in patch.supported_roles:
            return self._clamp(0.72 + allowed_bonus)
        return self._clamp(0.35 + allowed_bonus)

    def _clamp(self, value: float) -> float:
        return round(min(1.0, max(0.0, value)), 3)
