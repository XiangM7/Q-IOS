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
