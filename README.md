# Q-IOS Prototype

Q-IOS is a runtime operating layer for structure-governed, tokenized, patch-based execution. This prototype is a user-space simulation of the Q-IOS flow: a computational objective becomes a structured job model, then a phi-token, then an admissible execution assignment with snapshot and recovery support.

Important: this is not a bare-metal operating system. It is a Python runtime prototype designed to run on macOS or Linux.

## Architecture

The prototype enforces the core Q-IOS rule set:

1. A user objective does not execute directly.
2. The objective is transformed into a `StructuredJobModel`.
3. The structured job produces a `PhiToken`.
4. The token passes policy and admissibility checks.
5. The scheduler assigns the token to a patch domain.
6. The patch runtime executes or simulates execution.
7. Tasks, tokens, events, and snapshots are persisted in SQLite.
8. Failures recover through local fallback and reroute instead of a full restart.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python -m qios.main submit examples/task.json
python -m qios.main submit examples/failing_task.json
python -m qios.main events TASK_ID
python -m qios.main reset-state
```

## Simulation and Benchmarking

```bash
python -m qios.sim.runner \
  --tasks 1000 \
  --failure-rate 0.3 \
  --fallback-failure-rate 0.15 \
  --no-fallback-ratio 0.1 \
  --policy-invalid-ratio 0.05 \
  --congestion-rate 0.2 \
  --max-reroutes 3 \
  --systems qios,direct,retry_only,static \
  --seed 42
```

This benchmark runs one shared synthetic workload across Q-IOS and baseline systems, then compares completion rate, runtime failure rate, policy rejection rate, recovery success rate, latency, restarts, reroutes, fallback dispatches, quarantines, and reroute exhaustion.

Q-IOS recovery is intentionally bounded. Fallback dispatch can fail, reroutes can be exhausted, no-fallback tasks can terminate unrecovered, and policy-invalid tasks are rejected before runtime execution.

The latest benchmark artifacts are written under:

```text
runs/latest/metrics.csv
runs/latest/summary.json
runs/latest/report.md
```

## Patent-Aligned Control Plane Features

Q-IOS now includes a patent-aligned control plane layer around the existing runtime path. This adds phi-cache feedback, modulation profiles, local patch arbitration, snapshot packaging, replay-ledger tracking, and rollback anchors without changing the core submit CLI flow.

The simulation runner continues to compare Q-IOS against simpler baselines:

```bash
python -m qios.sim.runner \
  --tasks 1000 \
  --failure-rate 0.3 \
  --fallback-failure-rate 0.15 \
  --no-fallback-ratio 0.1 \
  --policy-invalid-ratio 0.05 \
  --congestion-rate 0.2 \
  --max-reroutes 3 \
  --systems qios,direct,retry_only,static \
  --seed 42
```

The benchmark report compares completion rate, runtime failure rate, policy rejection rate, recovery success rate, latency, full restarts, reroutes, fallback dispatches, quarantines, reroute exhaustion, and Q-IOS-specific control plane counters such as phi-cache hits, modulation profiles, arbitration outcomes, snapshots, rollback anchors, replay-ledger events, and local reentry count.

## Test

```bash
pytest
```

## State

Runtime state is created automatically under:

```text
.qios_state/qios.db
```

## Acceptance

- `python -m qios.main submit examples/task.json` runs successfully.
- `python -m qios.main submit examples/failing_task.json` shows failure, recovery, reassignment, and resumed execution.
- SQLite state is created under `.qios_state/qios.db`.
- Tests pass with `pytest`.
- The code is modular and easy to extend into a daemon or a future Rust implementation.
