from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RecoveryAction(str, Enum):
    NONE = "NONE"
    RETRY = "RETRY"
    REROUTE = "REROUTE"
    FALLBACK_DISPATCH = "FALLBACK_DISPATCH"
    SNAPSHOT_RESTORE = "SNAPSHOT_RESTORE"
    LOCAL_REENTRY = "LOCAL_REENTRY"
    QUARANTINE = "QUARANTINE"
    FAIL = "FAIL"


class RecoveryDecision(BaseModel):
    action: RecoveryAction
    reason: str
    target_patch_id: str | None = None
    target_route_id: str | None = None
    use_snapshot: bool = False
    use_rollback_anchor: bool = False
    should_quarantine_failed_patch: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class RecoveryPolicyEngine:
    def decide(
        self,
        token,
        failed_patch_id: str,
        failed_route_id: str | None,
        failed_patches: set[str],
        candidate_patch_ids: list[str],
        health_manager,
        route_evaluator,
        max_reroutes: int,
        current_reroutes: int,
        fallback_patch_id: str | None = None,
    ) -> RecoveryDecision:
        if current_reroutes >= max_reroutes:
            return RecoveryDecision(
                action=RecoveryAction.FAIL,
                reason="Maximum reroutes exhausted.",
                target_route_id=failed_route_id,
                metadata={"current_reroutes": current_reroutes, "max_reroutes": max_reroutes},
            )

        failed_score = health_manager.get_score(failed_patch_id)
        should_quarantine = health_manager.should_quarantine(failed_patch_id)
        ranked_candidates = health_manager.rank_by_health(candidate_patch_ids)
        viable_candidates = [
            (patch_id, health_score)
            for patch_id, health_score in ranked_candidates
            if patch_id != failed_patch_id
            and patch_id not in failed_patches
            and not health_manager.is_quarantined(patch_id)
        ]

        fallback_health = None
        if fallback_patch_id is not None:
            fallback_health = health_manager.get_score(fallback_patch_id).health_score

        best_patch_id = viable_candidates[0][0] if viable_candidates else None
        best_patch_health = viable_candidates[0][1] if viable_candidates else 0.0

        if fallback_patch_id is not None and fallback_patch_id not in failed_patches:
            fallback_is_viable = (
                not health_manager.is_quarantined(fallback_patch_id)
                and fallback_health is not None
                and fallback_health >= 0.55
            )
            if fallback_is_viable and (best_patch_id is None or fallback_health >= best_patch_health - 0.1):
                return RecoveryDecision(
                    action=RecoveryAction.FALLBACK_DISPATCH,
                    reason="Fallback patch is healthy enough for bounded recovery dispatch.",
                    target_patch_id=fallback_patch_id,
                    target_route_id=failed_route_id,
                    should_quarantine_failed_patch=should_quarantine,
                    metadata={
                        "failed_patch_health": failed_score.health_score,
                        "fallback_health": fallback_health,
                        "route_evaluator": route_evaluator.__class__.__name__,
                    },
                )

        if best_patch_id is not None and best_patch_health >= 0.55:
            return RecoveryDecision(
                action=RecoveryAction.REROUTE,
                reason="Healthy alternative patch available for survivable reroute.",
                target_patch_id=best_patch_id,
                target_route_id=failed_route_id,
                should_quarantine_failed_patch=should_quarantine,
                metadata={
                    "failed_patch_health": failed_score.health_score,
                    "selected_patch_health": best_patch_health,
                    "route_evaluator": route_evaluator.__class__.__name__,
                },
            )

        if token.metadata.get("rollback_anchor_id") and (best_patch_id or fallback_patch_id):
            return RecoveryDecision(
                action=RecoveryAction.LOCAL_REENTRY,
                reason="No healthy route available; attempting bounded local re-entry from rollback anchor.",
                target_patch_id=best_patch_id or fallback_patch_id,
                target_route_id=failed_route_id,
                use_rollback_anchor=True,
                should_quarantine_failed_patch=should_quarantine,
                metadata={"failed_patch_health": failed_score.health_score},
            )

        if token.metadata.get("replay_lineage") and (best_patch_id or fallback_patch_id):
            return RecoveryDecision(
                action=RecoveryAction.SNAPSHOT_RESTORE,
                reason="No healthy route available; using snapshot-style replay continuity.",
                target_patch_id=best_patch_id or fallback_patch_id,
                target_route_id=failed_route_id,
                use_snapshot=True,
                should_quarantine_failed_patch=should_quarantine,
                metadata={"failed_patch_health": failed_score.health_score},
            )

        return RecoveryDecision(
            action=RecoveryAction.FAIL,
            reason="No survivable recovery path available.",
            target_route_id=failed_route_id,
            should_quarantine_failed_patch=should_quarantine,
            metadata={"failed_patch_health": failed_score.health_score},
        )
