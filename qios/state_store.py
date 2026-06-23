from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from qios.models import ExecutionEvent, PhiToken, SnapshotPackage, TaskRequest


class StateStore:
    def __init__(self, base_dir: str | Path = ".qios_state") -> None:
        self.base_dir = Path(base_dir)
        self.db_path = self.base_dir / "qios.db"
        self.init_db()

    def init_db(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tokens (
                    token_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    state TEXT NOT NULL,
                    assigned_patch TEXT,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    message TEXT NOT NULL,
                    patch TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save_task(self, task: TaskRequest) -> None:
        payload = task.model_dump_json()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO tasks (task_id, objective, priority, payload, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (task.task_id, task.objective, task.priority, payload),
            )

    def save_token(self, token: PhiToken) -> None:
        payload = token.model_dump_json()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO tokens (token_id, task_id, role, state, assigned_patch, payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    token.token_id,
                    token.task_id,
                    token.role,
                    token.lifecycle_state.value,
                    token.assigned_patch,
                    payload,
                ),
            )

    def save_event(self, event: ExecutionEvent) -> None:
        payload = event.model_dump_json()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO events (event_id, task_id, token_id, event_type, state, message, patch, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.token_id,
                    event.event_type,
                    event.state.value,
                    event.message,
                    event.patch,
                    payload,
                    event.created_at.isoformat(),
                ),
            )

    def save_snapshot(self, snapshot: SnapshotPackage) -> None:
        payload = snapshot.model_dump_json()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO snapshots (snapshot_id, task_id, token_id, state, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.task_id,
                    snapshot.token_id,
                    snapshot.lifecycle_state.value,
                    payload,
                    snapshot.created_at.isoformat(),
                ),
            )

    def list_events(self, task_id: str) -> list[ExecutionEvent]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM events
                WHERE task_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (task_id,),
            ).fetchall()
        return [ExecutionEvent.model_validate_json(row[0]) for row in rows]

    def get_latest_snapshot(self, task_id: str) -> SnapshotPackage | None:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM snapshots
                WHERE task_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return SnapshotPackage.model_validate_json(row[0])

    def reset_state(self) -> None:
        if self.base_dir.exists():
            shutil.rmtree(self.base_dir)
        self.init_db()
