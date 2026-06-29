# NP1 Code Mapping

This repository currently covers the runtime control-plane version of NP1:
phi-token generation, patch-indexed modulation scoring, patch-local arbitration,
and phi-cache feedback.

It does not yet fully implement real neural embedding replacement, dense embedding
table substitution, transformer attention layer integration, or patch-resident
replacement embedding tensor generation.

| NP1 Reference | Patent Meaning | Code Location | Implementation Notes |
| --- | --- | --- | --- |
| FIG. 1 / 122 | One or more phi-tokens | `qios/models.py` / `PhiToken` | Runtime token object for identity, role, localization, fallback, and modulation state. |
| FIG. 1 / 130 | Token parser / metadata extractor | `qios/token_engine.py` / `PhiTokenEngine.create_token()` | Extracts structured-job metadata into a phi-token. |
| FIG. 1 / 140 | Phi-to-weight preparation | `qios/token_engine.py` / `PhiTokenEngine.create_token()` | Uses deterministic `phi_modulation` preparation instead of a learned weighting block. |
| FIG. 1 / 150 | Patch-indexed modulation profile generator | `qios/control/modulation_profile.py` / `ModulationProfileGenerator.generate()` | Builds per-patch modulation scores from role, priority, cache, health, and congestion. |
| FIG. 1 / 170 | Patch-local arbitration logic | `qios/control/patch_arbitration.py` / `PatchLocalArbitrator.arbitrate()` | Applies local threshold-based arbitration over candidate patches. |
| FIG. 1 / 190 | Phi-cache persistent store | `qios/control/phi_cache.py` / `PhiCacheEntry`, `PhiCache` | Tracks success, failure, latency, and reroute feedback for later affinity scoring. |
| FIG. 2 / 205 | Create or receive phi-token | `qios/token_engine.py` / `PhiTokenEngine.create_token()` | Converts a structured job into a runtime phi-token. |
| FIG. 2 / 210 | Extract identity/context metadata and role tag | `qios/token_engine.py` / `PhiTokenEngine.create_token()` | Moves task/job context into token metadata and role fields. |
| FIG. 2 / 215 | Determine execution-localization fields | `qios/token_engine.py` / `PhiTokenEngine.create_token()`, `_infer_patch_hint()` | Assigns patch hint, priority, and fallback routing hints. |
| FIG. 2 / 222 | Check whether cached affinity data exists | `qios/sim/baselines.py` / `QIOSSimulationSystem._select_patch_with_control()` | Uses `PhiCacheEntry.has_history` to gate whether prior affinity data exists. |
| FIG. 2 / 220 | Access phi-cache state | `qios/control/phi_cache.py`, `qios/sim/baselines.py` / `_select_patch_with_control()` | Reads feedback state before recomputing candidate affinity. |
| FIG. 2 / 225 | Encode patch-indexed modulation values | `qios/control/modulation_profile.py` / `PatchModulationScore`, `generate()` | Produces deterministic weighted per-patch modulation scores. |
| FIG. 2 / 230 | Assemble modulation profile | `qios/control/modulation_profile.py` / `ModulationProfile` | Bundles candidate patch scores into one profile. |
| FIG. 2 / 245 | Output profile to local arbitration | `qios/sim/baselines.py` / `_select_patch_with_control()` | Sends the assembled profile into patch-local arbitration. |
| FIG. 3 / 305 | Receive local candidate subset | `qios/control/patch_arbitration.py` / `arbitrate()` | Works over the locally selected candidate set only. |
| FIG. 3 / 315 | Compare against local conditions | `qios/control/patch_arbitration.py` / `arbitrate()` | Evaluates health, congestion, and score thresholds. |
| FIG. 3 / 320 | Determine whether condition is satisfied | `qios/control/patch_arbitration.py` / `arbitrate()` | Uses threshold branches for accept, reroute, defer, reject, and quarantine. |
| FIG. 3 / 325 | Local arbitration decision | `qios/control/patch_arbitration.py` / `ArbitrationDecision`, `arbitrate()` | Produces the local arbitration outcome. |
| FIG. 3 / 330 | Accepted local routing output | `qios/sim/baselines.py` / `_select_patch_with_control()` | Uses arbitration outcome counters and selected patch output. |
| FIG. 3 / 345 | Execution produces outcome data | `qios/sim/baselines.py` / `_execute_attempt()` | Captures success/failure after runtime execution. |
| FIG. 3 / 350 | Outcome enters feedback path | `qios/sim/baselines.py` / `_execute_attempt()` | Sends execution outcomes into cache and telemetry feedback. |
| FIG. 4 / 405 | Outcome data arrives at feedback stage | `qios/sim/baselines.py` / `_execute_attempt()` | Execution results are translated into update signals. |
| FIG. 4 / 410 | Store outcome data | `qios/control/phi_cache.py` / `PhiCacheEntry` | Persists success/failure/latency/reroute state per patch and role. |
| FIG. 4 / 420 | Classify and combine feedback | `qios/control/phi_cache.py` / `_recompute_preference()` | Combines success, failure, reroute, latency, and health into one affinity score. |
| FIG. 4 / 430 | Strengthen successful affinity | `qios/control/phi_cache.py` / `update_success()`, `qios/sim/baselines.py` / `_execute_attempt()` | Success increases or preserves patch affinity. |
| FIG. 4 / 440 | Decay failed affinity | `qios/control/phi_cache.py` / `update_failure()`, `qios/sim/baselines.py` / `_execute_attempt()` | Failure lowers affinity and marks the route as less desirable. |
| FIG. 4 / 445 | Feed reroute history back into modulation | `qios/control/phi_cache.py` / `update_reroute()`, `qios/sim/baselines.py` / `run()` | Reroute history influences future patch scoring. |
| FIG. 4 / 450 | Recompute later affinity state | `qios/control/phi_cache.py` / `_recompute_preference()` | Produces the next deterministic affinity score used by later modulation. |
