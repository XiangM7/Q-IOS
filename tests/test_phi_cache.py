from qios.control import PhiCache


def test_phi_cache_updates_history_and_preference_scores() -> None:
    cache = PhiCache()
    entry = cache.get_entry("analysis_patch", "analysis")

    assert entry.has_history is False
    baseline_score = entry.preference_score

    cache.update_success("analysis_patch", "analysis", latency_ms=18.0, health_score=0.94)
    updated = cache.get_entry("analysis_patch", "analysis")

    assert updated.has_history is True
    assert updated.success_count == 1
    assert updated.average_latency_ms == 18.0
    assert updated.preference_score > baseline_score


def test_phi_cache_ranks_patches_by_observed_feedback() -> None:
    cache = PhiCache()
    cache.update_success("analysis_patch", "analysis", latency_ms=12.0, health_score=0.96)
    cache.update_failure("sandbox_patch", "analysis", latency_ms=40.0, health_score=0.5)

    ranked = cache.rank_patches(["sandbox_patch", "analysis_patch"], "analysis")

    assert ranked[0][0] == "analysis_patch"
    assert ranked[0][1] > ranked[1][1]
