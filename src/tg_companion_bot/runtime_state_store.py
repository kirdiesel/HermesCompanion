from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .live_runtime import RuntimeState
from .state_codec import STATE_SCHEMA_VERSION, runtime_state_from_dict, runtime_state_to_dict


class RuntimeStateStoreError(RuntimeError):
    """Raised when durable runtime state cannot be read or committed."""


class SQLiteRuntimeStateStore:
    """Transactional single-runtime-state store for a live Hermes bridge."""

    def __init__(self, path: Path | str, *, busy_timeout: float = 5.0):
        self.path = Path(path)
        self.busy_timeout = max(float(busy_timeout), 0.0)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runtime_state (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        schema_version INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
        except sqlite3.Error as error:
            raise RuntimeStateStoreError(f"Cannot initialize runtime state store: {error}") from error

    def load(self, *, obsidian_root: Path | str | None = None) -> RuntimeState:
        self.initialize()
        try:
            with self._connect() as connection:
                return self._load_from_connection(connection, obsidian_root=obsidian_root)
        except (sqlite3.Error, ValueError) as error:
            raise RuntimeStateStoreError(f"Cannot load runtime state: {error}") from error

    def revision(self) -> int:
        self.initialize()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT revision FROM runtime_state WHERE singleton = 1"
                ).fetchone()
        except sqlite3.Error as error:
            raise RuntimeStateStoreError(f"Cannot read runtime state revision: {error}") from error
        return int(row[0]) if row is not None else 0

    @contextmanager
    def transaction(
        self,
        *,
        obsidian_root: Path | str | None = None,
    ) -> Iterator[RuntimeState]:
        """Yield state under `BEGIN IMMEDIATE` and commit only real changes."""

        self.initialize()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            state = self._load_from_connection(connection, obsidian_root=obsidian_root)
            before = _canonical_payload(state)
            yield state
            after = _canonical_payload(state)
            if after != before:
                self._write_to_connection(connection, after)
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error, (RuntimeStateStoreError, sqlite3.Error)):
                raise RuntimeStateStoreError(f"Runtime state transaction failed: {error}") from error
            raise
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout,
            isolation_level=None,
        )
        connection.execute(f"PRAGMA busy_timeout={int(self.busy_timeout * 1000)}")
        return connection

    def _load_from_connection(
        self,
        connection: sqlite3.Connection,
        *,
        obsidian_root: Path | str | None,
    ) -> RuntimeState:
        row = connection.execute(
            "SELECT schema_version, payload FROM runtime_state WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return RuntimeState(
                obsidian_root=Path(obsidian_root) if obsidian_root is not None else None
            )
        schema_version, payload_text = row
        if int(schema_version) != STATE_SCHEMA_VERSION:
            raise RuntimeStateStoreError(
                f"Unsupported database state schema version: {schema_version!r}"
            )
        payload = json.loads(str(payload_text))
        return runtime_state_from_dict(payload, obsidian_root=obsidian_root)

    def _write_to_connection(self, connection: sqlite3.Connection, payload: str) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            """
            INSERT INTO runtime_state (
                singleton, schema_version, payload, revision, updated_at
            ) VALUES (1, ?, ?, 1, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                schema_version = excluded.schema_version,
                payload = excluded.payload,
                revision = runtime_state.revision + 1,
                updated_at = excluded.updated_at
            """,
            (STATE_SCHEMA_VERSION, payload, now),
        )


def _canonical_payload(state: RuntimeState) -> str:
    return json.dumps(
        runtime_state_to_dict(state),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
