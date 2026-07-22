from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


OUTBOX_STATUSES = frozenset(
    {
        "pending",
        "leased",
        "sending",
        "retry",
        "sent",
        "uncertain",
        "expired",
        "dead_letter",
    }
)
SEND_OUTCOMES = frozenset({"sent", "retryable", "uncertain", "permanent"})
MAX_SPOOL_FILE_BYTES = 1_048_576
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SPOOL_CLAIM_LOCK = threading.Lock()


class DeliveryStoreError(RuntimeError):
    """Raised when proactive delivery state cannot be read or committed."""


class DeliveryStateError(DeliveryStoreError):
    """Raised for an invalid outbox state transition."""


class SpoolError(RuntimeError):
    """Raised when an atomic spool operation fails."""


class SpoolValidationError(SpoolError):
    """A safe, content-free validation error suitable for quarantine."""

    def __init__(self, code: str):
        _validate_code(code, field="spool error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class IntakeEvent:
    envelope_id: str
    dedupe_key: str
    content_hash: str
    source: str
    kind: str
    generated_at: datetime
    payload: Mapping[str, Any]
    batch_key: str | None = None


@dataclass(frozen=True)
class EntityRevision:
    entity_key: str
    revision_key: str
    observed_at: datetime
    payload: Mapping[str, Any]
    topic_key: str | None = None


@dataclass(frozen=True)
class DeliveryCandidate:
    delivery_key: str
    action_kind: str
    payload: Mapping[str, Any]
    expires_at: datetime
    available_at: datetime | None = None


@dataclass(frozen=True)
class IngestResult:
    status: str
    envelope_id: str
    inserted_revisions: int = 0
    inserted_outbox: int = 0
    outbox_ids: tuple[str, ...] = ()
    conflict_reason: str | None = None


@dataclass(frozen=True)
class BatchEnqueueResult:
    status: str
    batch_key: str
    inserted_outbox: int = 0
    outbox_ids: tuple[str, ...] = ()
    conflict_reason: str | None = None


@dataclass(frozen=True)
class OutboxRecord:
    outbox_id: str
    delivery_key: str
    action_kind: str
    payload: dict[str, Any]
    status: str
    attempt_count: int
    available_at: datetime
    expires_at: datetime
    lease_until: datetime | None = None
    leased_by: str | None = None
    message_id: str | None = None
    last_error_code: str | None = None


@dataclass(frozen=True)
class SendOutcome:
    status: str
    message_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status not in SEND_OUTCOMES:
            raise ValueError(f"Unsupported send outcome: {self.status!r}")
        if self.status == "sent" and not self.message_id:
            raise ValueError("A sent outcome requires message_id")
        if self.status != "sent" and not self.error_code:
            raise ValueError(f"A {self.status} outcome requires error_code")
        if self.error_code is not None:
            _validate_code(self.error_code, field="delivery error code")

    @classmethod
    def sent(cls, message_id: str) -> SendOutcome:
        return cls(status="sent", message_id=str(message_id))

    @classmethod
    def retryable(cls, error_code: str) -> SendOutcome:
        return cls(status="retryable", error_code=error_code)

    @classmethod
    def uncertain(cls, error_code: str) -> SendOutcome:
        return cls(status="uncertain", error_code=error_code)

    @classmethod
    def permanent(cls, error_code: str) -> SendOutcome:
        return cls(status="permanent", error_code=error_code)


@dataclass(frozen=True)
class DeliveryStepResult:
    status: str
    outbox_id: str | None = None
    resulting_status: str | None = None


@dataclass(frozen=True)
class SpoolLayout:
    root: Path

    @property
    def incoming(self) -> Path:
        return self.root / "incoming"

    @property
    def processing(self) -> Path:
        return self.root / "processing"

    @property
    def archive(self) -> Path:
        return self.root / "archive"

    @property
    def quarantine(self) -> Path:
        return self.root / "quarantine"

    def initialize(self) -> None:
        for directory in (self.incoming, self.processing, self.archive, self.quarantine):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SpoolClaim:
    path: Path


@dataclass(frozen=True)
class SpoolProcessResult:
    status: str
    path: Path | None = None
    error_code: str | None = None


class SQLiteDeliveryOutbox:
    """Separate durable intake, revision and delivery tables for proactive messages."""

    def __init__(self, path: Path | str, *, busy_timeout: float = 5.0):
        self.path = Path(path)
        self.busy_timeout = max(float(busy_timeout), 0.0)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS proactive_intake_events (
                        envelope_id TEXT PRIMARY KEY,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        content_hash TEXT NOT NULL,
                        source TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        batch_key TEXT,
                        generated_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        conflict_reason TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS proactive_entity_revisions (
                        entity_key TEXT NOT NULL,
                        revision_key TEXT NOT NULL,
                        topic_key TEXT,
                        observed_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (entity_key, revision_key)
                    );

                    CREATE TABLE IF NOT EXISTS proactive_outbox (
                        outbox_id TEXT PRIMARY KEY,
                        delivery_key TEXT NOT NULL UNIQUE,
                        action_kind TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        available_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        lease_until TEXT,
                        leased_by TEXT,
                        message_id TEXT,
                        last_error_code TEXT,
                        created_at TEXT NOT NULL,
                        sent_at TEXT
                    );

                    CREATE INDEX IF NOT EXISTS proactive_outbox_ready_idx
                    ON proactive_outbox(status, available_at, expires_at);

                    CREATE TABLE IF NOT EXISTS proactive_batches (
                        batch_key TEXT PRIMARY KEY,
                        content_hash TEXT NOT NULL,
                        status TEXT NOT NULL,
                        conflict_reason TEXT,
                        closed_at TEXT NOT NULL
                    );
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(proactive_intake_events)")
                }
                if "batch_key" not in columns:
                    connection.execute(
                        "ALTER TABLE proactive_intake_events ADD COLUMN batch_key TEXT"
                    )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS proactive_intake_batch_idx
                    ON proactive_intake_events(batch_key, generated_at, envelope_id)
                    """
                )
        except sqlite3.Error as error:
            raise DeliveryStoreError(f"Cannot initialize proactive delivery store: {error}") from error

    def ingest(
        self,
        event: IntakeEvent,
        *,
        revisions: Iterable[EntityRevision] = (),
        deliveries: Iterable[DeliveryCandidate] = (),
        now: datetime | None = None,
    ) -> IngestResult:
        self.initialize()
        clock = _aware(now or datetime.now(timezone.utc), field="now")
        generated_at = _aware(event.generated_at, field="generated_at")
        _require_text(event.envelope_id, field="envelope_id")
        _require_text(event.dedupe_key, field="dedupe_key")
        _require_text(event.content_hash, field="content_hash")
        _require_text(event.source, field="source")
        _require_text(event.kind, field="kind")
        payload_json = _canonical_json(event.payload)
        revision_rows = tuple(revisions)
        delivery_rows = tuple(deliveries)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT envelope_id, dedupe_key, content_hash
                FROM proactive_intake_events
                WHERE envelope_id = ? OR dedupe_key = ?
                ORDER BY CASE WHEN envelope_id = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (event.envelope_id, event.dedupe_key, event.envelope_id),
            ).fetchone()
            if existing is not None:
                same_identity = (
                    str(existing["envelope_id"]) == event.envelope_id
                    and str(existing["dedupe_key"]) == event.dedupe_key
                )
                same_hash = str(existing["content_hash"]) == event.content_hash
                if same_identity and same_hash:
                    connection.commit()
                    return IngestResult(status="duplicate", envelope_id=event.envelope_id)
                reason = "identity_hash_mismatch"
                connection.execute(
                    """
                    UPDATE proactive_intake_events
                    SET status = 'conflict', conflict_reason = ?
                    WHERE envelope_id = ?
                    """,
                    (reason, str(existing["envelope_id"])),
                )
                connection.commit()
                return IngestResult(
                    status="conflict",
                    envelope_id=event.envelope_id,
                    conflict_reason=reason,
                )

            connection.execute(
                """
                INSERT INTO proactive_intake_events (
                    envelope_id, dedupe_key, content_hash, source, kind, batch_key,
                    generated_at, status, payload_json, conflict_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ingested', ?, NULL, ?)
                """,
                (
                    event.envelope_id,
                    event.dedupe_key,
                    event.content_hash,
                    event.source,
                    event.kind,
                    event.batch_key,
                    _time_text(generated_at),
                    payload_json,
                    _time_text(clock),
                ),
            )

            inserted_revisions = 0
            for revision in revision_rows:
                _require_text(revision.entity_key, field="entity_key")
                _require_text(revision.revision_key, field="revision_key")
                observed_at = _aware(revision.observed_at, field="observed_at")
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO proactive_entity_revisions (
                        entity_key, revision_key, topic_key, observed_at,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        revision.entity_key,
                        revision.revision_key,
                        revision.topic_key,
                        _time_text(observed_at),
                        _canonical_json(revision.payload),
                        _time_text(clock),
                    ),
                )
                inserted_revisions += int(cursor.rowcount > 0)

            outbox_ids: list[str] = []
            for delivery in delivery_rows:
                _require_text(delivery.delivery_key, field="delivery_key")
                _require_text(delivery.action_kind, field="action_kind")
                expires_at = _aware(delivery.expires_at, field="expires_at")
                available_at = _aware(delivery.available_at or clock, field="available_at")
                outbox_id = _outbox_id(delivery.delivery_key)
                status = "expired" if expires_at <= clock else "pending"
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO proactive_outbox (
                        outbox_id, delivery_key, action_kind, payload_json, status,
                        attempt_count, available_at, expires_at, lease_until,
                        leased_by, message_id, last_error_code, created_at, sent_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, NULL, NULL, ?, NULL)
                    """,
                    (
                        outbox_id,
                        delivery.delivery_key,
                        delivery.action_kind,
                        _canonical_json(delivery.payload),
                        status,
                        _time_text(available_at),
                        _time_text(expires_at),
                        _time_text(clock),
                    ),
                )
                if cursor.rowcount > 0:
                    outbox_ids.append(outbox_id)

            connection.commit()
            return IngestResult(
                status="inserted",
                envelope_id=event.envelope_id,
                inserted_revisions=inserted_revisions,
                inserted_outbox=len(outbox_ids),
                outbox_ids=tuple(outbox_ids),
            )
        except (sqlite3.Error, TypeError, ValueError) as error:
            connection.rollback()
            if isinstance(error, DeliveryStoreError):
                raise
            raise DeliveryStoreError(f"Cannot ingest proactive envelope: {error}") from error
        finally:
            connection.close()

    def batch_payloads(self, batch_key: str) -> tuple[dict[str, Any], ...]:
        """Load successfully ingested batch members in deterministic producer order."""

        self.initialize()
        _require_text(batch_key, field="batch_key")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json FROM proactive_intake_events
                    WHERE batch_key = ? AND status = 'ingested'
                    ORDER BY generated_at, envelope_id
                    """,
                    (batch_key,),
                ).fetchall()
        except sqlite3.Error as error:
            raise DeliveryStoreError(f"Cannot read proactive batch: {error}") from error
        payloads: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                raise DeliveryStoreError("Intake payload must decode to an object")
            payloads.append(payload)
        return tuple(payloads)

    def open_batch_keys(self, *, limit: int = 100) -> tuple[str, ...]:
        """List ingested, not-yet-closed batches in deterministic oldest-first order."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer between 1 and 1000")
        self.initialize()
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT intake.batch_key, MIN(intake.generated_at) AS first_generated_at
                    FROM proactive_intake_events AS intake
                    LEFT JOIN proactive_batches AS batch
                      ON batch.batch_key = intake.batch_key
                    WHERE intake.batch_key IS NOT NULL
                      AND intake.status = 'ingested'
                      AND batch.batch_key IS NULL
                    GROUP BY intake.batch_key
                    ORDER BY first_generated_at, intake.batch_key
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as error:
            raise DeliveryStoreError(f"Cannot list open proactive batches: {error}") from error
        return tuple(str(row["batch_key"]) for row in rows)

    def enqueue_batch(
        self,
        *,
        batch_key: str,
        content_hash: str,
        deliveries: Iterable[DeliveryCandidate],
        now: datetime | None = None,
    ) -> BatchEnqueueResult:
        """Close one deterministic batch and insert all resulting actions atomically."""

        self.initialize()
        _require_text(batch_key, field="batch_key")
        _require_text(content_hash, field="content_hash")
        clock = _aware(now or datetime.now(timezone.utc), field="now")
        delivery_rows = tuple(deliveries)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT content_hash, status FROM proactive_batches WHERE batch_key = ?",
                (batch_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["content_hash"]) == content_hash:
                    connection.commit()
                    return BatchEnqueueResult(status="duplicate", batch_key=batch_key)
                reason = "batch_content_changed_after_close"
                connection.execute(
                    """
                    UPDATE proactive_batches
                    SET status = 'conflict', conflict_reason = ?
                    WHERE batch_key = ?
                    """,
                    (reason, batch_key),
                )
                connection.commit()
                return BatchEnqueueResult(
                    status="conflict",
                    batch_key=batch_key,
                    conflict_reason=reason,
                )

            connection.execute(
                """
                INSERT INTO proactive_batches (
                    batch_key, content_hash, status, conflict_reason, closed_at
                ) VALUES (?, ?, 'closed', NULL, ?)
                """,
                (batch_key, content_hash, _time_text(clock)),
            )
            outbox_ids = self._insert_deliveries(connection, delivery_rows, clock)
            connection.commit()
            return BatchEnqueueResult(
                status="inserted",
                batch_key=batch_key,
                inserted_outbox=len(outbox_ids),
                outbox_ids=tuple(outbox_ids),
            )
        except (sqlite3.Error, TypeError, ValueError) as error:
            connection.rollback()
            raise DeliveryStoreError(f"Cannot enqueue proactive batch: {error}") from error
        finally:
            connection.close()

    def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        lease_seconds: float = 60.0,
    ) -> OutboxRecord | None:
        self.initialize()
        _require_text(worker_id, field="worker_id")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        clock = _aware(now or datetime.now(timezone.utc), field="now")
        lease_until = clock + timedelta(seconds=float(lease_seconds))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._expire_and_recover(connection, clock)
            row = connection.execute(
                """
                SELECT * FROM proactive_outbox
                WHERE status IN ('pending', 'retry')
                  AND available_at <= ?
                  AND expires_at > ?
                ORDER BY available_at, created_at, outbox_id
                LIMIT 1
                """,
                (_time_text(clock), _time_text(clock)),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE proactive_outbox
                SET status = 'leased', attempt_count = attempt_count + 1,
                    leased_by = ?, lease_until = ?
                WHERE outbox_id = ?
                """,
                (worker_id, _time_text(lease_until), str(row["outbox_id"])),
            )
            claimed = connection.execute(
                "SELECT * FROM proactive_outbox WHERE outbox_id = ?",
                (str(row["outbox_id"]),),
            ).fetchone()
            connection.commit()
            return _outbox_from_row(claimed)
        except sqlite3.Error as error:
            connection.rollback()
            raise DeliveryStoreError(f"Cannot claim proactive delivery: {error}") from error
        finally:
            connection.close()

    def acknowledge(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        message_id: str,
        now: datetime | None = None,
    ) -> None:
        _require_text(message_id, field="message_id")
        self._finish_lease(
            outbox_id,
            worker_id=worker_id,
            status="sent",
            now=now,
            message_id=message_id,
        )

    def begin_send(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> OutboxRecord:
        """Mark the network-attempt boundary so crash recovery never retries it blindly."""

        self.initialize()
        _require_text(outbox_id, field="outbox_id")
        _require_text(worker_id, field="worker_id")
        clock = _aware(now or datetime.now(timezone.utc), field="now")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, leased_by, lease_until, expires_at
                FROM proactive_outbox WHERE outbox_id = ?
                """,
                (outbox_id,),
            ).fetchone()
            if row is None:
                raise DeliveryStateError("Unknown outbox_id")
            if str(row["status"]) != "leased" or str(row["leased_by"]) != worker_id:
                raise DeliveryStateError("Outbox row is not leased by this worker")
            if not row["lease_until"] or _time_from_text(str(row["lease_until"])) <= clock:
                raise DeliveryStateError("Outbox lease expired before send started")
            if _time_from_text(str(row["expires_at"])) <= clock:
                raise DeliveryStateError("Outbox delivery expired before send started")
            connection.execute(
                "UPDATE proactive_outbox SET status = 'sending' WHERE outbox_id = ?",
                (outbox_id,),
            )
            updated = connection.execute(
                "SELECT * FROM proactive_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()
            connection.commit()
            return _outbox_from_row(updated)
        except DeliveryStateError:
            connection.rollback()
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise DeliveryStoreError(f"Cannot start proactive delivery attempt: {error}") from error
        finally:
            connection.close()

    def retry(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        error_code: str,
        available_at: datetime,
        now: datetime | None = None,
    ) -> None:
        _validate_code(error_code, field="delivery error code")
        clock = _aware(now or datetime.now(timezone.utc), field="now")
        retry_at = _aware(available_at, field="available_at")
        self._finish_lease(
            outbox_id,
            worker_id=worker_id,
            status="retry",
            now=clock,
            available_at=retry_at,
            error_code=error_code,
        )

    def mark_uncertain(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        error_code: str,
        now: datetime | None = None,
    ) -> None:
        _validate_code(error_code, field="delivery error code")
        self._finish_lease(
            outbox_id,
            worker_id=worker_id,
            status="uncertain",
            now=now,
            error_code=error_code,
        )

    def dead_letter(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        error_code: str,
        now: datetime | None = None,
    ) -> None:
        _validate_code(error_code, field="delivery error code")
        self._finish_lease(
            outbox_id,
            worker_id=worker_id,
            status="dead_letter",
            now=now,
            error_code=error_code,
        )

    def get(self, outbox_id: str) -> OutboxRecord | None:
        self.initialize()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM proactive_outbox WHERE outbox_id = ?",
                    (outbox_id,),
                ).fetchone()
        except sqlite3.Error as error:
            raise DeliveryStoreError(f"Cannot read proactive delivery: {error}") from error
        return _outbox_from_row(row) if row is not None else None

    def count(self, *, table: str, status: str | None = None) -> int:
        table_names = {
            "intake": "proactive_intake_events",
            "revisions": "proactive_entity_revisions",
            "outbox": "proactive_outbox",
            "batches": "proactive_batches",
        }
        if table not in table_names:
            raise ValueError(f"Unsupported table alias: {table!r}")
        if status is not None and table != "outbox":
            raise ValueError("status filtering is available only for outbox")
        self.initialize()
        query = f"SELECT COUNT(*) FROM {table_names[table]}"
        arguments: tuple[Any, ...] = ()
        if status is not None:
            if status not in OUTBOX_STATUSES:
                raise ValueError(f"Unsupported outbox status: {status!r}")
            query += " WHERE status = ?"
            arguments = (status,)
        try:
            with self._connect() as connection:
                row = connection.execute(query, arguments).fetchone()
        except sqlite3.Error as error:
            raise DeliveryStoreError(f"Cannot count proactive records: {error}") from error
        return int(row[0])

    def _finish_lease(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        status: str,
        now: datetime | None,
        message_id: str | None = None,
        available_at: datetime | None = None,
        error_code: str | None = None,
    ) -> None:
        self.initialize()
        _require_text(outbox_id, field="outbox_id")
        _require_text(worker_id, field="worker_id")
        if status not in {"sent", "retry", "uncertain", "dead_letter"}:
            raise ValueError(f"Unsupported terminal transition: {status!r}")
        clock = _aware(now or datetime.now(timezone.utc), field="now")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, leased_by, expires_at FROM proactive_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()
            if row is None:
                raise DeliveryStateError("Unknown outbox_id")
            if str(row["status"]) != "sending" or str(row["leased_by"]) != worker_id:
                raise DeliveryStateError("Outbox row is not being sent by this worker")
            expires_at = _time_from_text(str(row["expires_at"]))
            final_status = status
            next_available = available_at or clock
            if status == "retry" and next_available >= expires_at:
                final_status = "expired"
            connection.execute(
                """
                UPDATE proactive_outbox
                SET status = ?, available_at = ?, lease_until = NULL, leased_by = NULL,
                    message_id = ?, last_error_code = ?, sent_at = ?
                WHERE outbox_id = ?
                """,
                (
                    final_status,
                    _time_text(next_available),
                    message_id,
                    error_code,
                    _time_text(clock) if final_status == "sent" else None,
                    outbox_id,
                ),
            )
            connection.commit()
        except DeliveryStateError:
            connection.rollback()
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise DeliveryStoreError(f"Cannot update proactive delivery: {error}") from error
        finally:
            connection.close()

    def _insert_deliveries(
        self,
        connection: sqlite3.Connection,
        deliveries: Iterable[DeliveryCandidate],
        clock: datetime,
    ) -> list[str]:
        outbox_ids: list[str] = []
        for delivery in deliveries:
            _require_text(delivery.delivery_key, field="delivery_key")
            _require_text(delivery.action_kind, field="action_kind")
            expires_at = _aware(delivery.expires_at, field="expires_at")
            available_at = _aware(delivery.available_at or clock, field="available_at")
            outbox_id = _outbox_id(delivery.delivery_key)
            status = "expired" if expires_at <= clock else "pending"
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO proactive_outbox (
                    outbox_id, delivery_key, action_kind, payload_json, status,
                    attempt_count, available_at, expires_at, lease_until,
                    leased_by, message_id, last_error_code, created_at, sent_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, NULL, NULL, ?, NULL)
                """,
                (
                    outbox_id,
                    delivery.delivery_key,
                    delivery.action_kind,
                    _canonical_json(delivery.payload),
                    status,
                    _time_text(available_at),
                    _time_text(expires_at),
                    _time_text(clock),
                ),
            )
            if cursor.rowcount > 0:
                outbox_ids.append(outbox_id)
        return outbox_ids

    def _expire_and_recover(self, connection: sqlite3.Connection, clock: datetime) -> None:
        timestamp = _time_text(clock)
        connection.execute(
            """
            UPDATE proactive_outbox
            SET status = 'expired', lease_until = NULL, leased_by = NULL
            WHERE status IN ('pending', 'retry', 'leased', 'sending') AND expires_at <= ?
            """,
            (timestamp,),
        )
        connection.execute(
            """
            UPDATE proactive_outbox
            SET status = 'uncertain', lease_until = NULL, leased_by = NULL,
                last_error_code = 'worker_lost_after_send_started'
            WHERE status = 'sending' AND lease_until <= ? AND expires_at > ?
            """,
            (timestamp, timestamp),
        )
        connection.execute(
            """
            UPDATE proactive_outbox
            SET status = 'retry', available_at = ?, lease_until = NULL, leased_by = NULL,
                last_error_code = 'lease_expired'
            WHERE status = 'leased' AND lease_until <= ? AND expires_at > ?
            """,
            (timestamp, timestamp, timestamp),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={int(self.busy_timeout * 1000)}")
        return connection


def run_delivery_step(
    store: SQLiteDeliveryOutbox,
    sender: Callable[[OutboxRecord], SendOutcome],
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_seconds: float = 60.0,
    retry_delay: timedelta = timedelta(minutes=1),
) -> DeliveryStepResult:
    """Execute one delivery through an injected sender; this function has no network imports."""

    clock = _aware(now or datetime.now(timezone.utc), field="now")
    record = store.claim_next(worker_id=worker_id, now=clock, lease_seconds=lease_seconds)
    if record is None:
        return DeliveryStepResult(status="idle")
    record = store.begin_send(record.outbox_id, worker_id=worker_id, now=clock)
    try:
        outcome = sender(record)
    except Exception:
        store.mark_uncertain(
            record.outbox_id,
            worker_id=worker_id,
            error_code="sender_exception",
            now=clock,
        )
        return DeliveryStepResult(
            status="processed",
            outbox_id=record.outbox_id,
            resulting_status="uncertain",
        )
    if not isinstance(outcome, SendOutcome):
        store.mark_uncertain(
            record.outbox_id,
            worker_id=worker_id,
            error_code="invalid_sender_outcome",
            now=clock,
        )
        return DeliveryStepResult(
            status="processed",
            outbox_id=record.outbox_id,
            resulting_status="uncertain",
        )
    if outcome.status == "sent":
        store.acknowledge(
            record.outbox_id,
            worker_id=worker_id,
            message_id=outcome.message_id or "",
            now=clock,
        )
        resulting = "sent"
    elif outcome.status == "retryable":
        store.retry(
            record.outbox_id,
            worker_id=worker_id,
            error_code=outcome.error_code or "retryable_failure",
            available_at=clock + retry_delay,
            now=clock,
        )
        refreshed = store.get(record.outbox_id)
        resulting = refreshed.status if refreshed is not None else "retry"
    elif outcome.status == "uncertain":
        store.mark_uncertain(
            record.outbox_id,
            worker_id=worker_id,
            error_code=outcome.error_code or "ambiguous_timeout",
            now=clock,
        )
        resulting = "uncertain"
    else:
        store.dead_letter(
            record.outbox_id,
            worker_id=worker_id,
            error_code=outcome.error_code or "permanent_failure",
            now=clock,
        )
        resulting = "dead_letter"
    return DeliveryStepResult(
        status="processed",
        outbox_id=record.outbox_id,
        resulting_status=resulting,
    )


def write_spool_atomic(layout: SpoolLayout, payload: bytes) -> Path:
    """Write bytes as a completed content-addressed file using temp + atomic replace."""

    layout.initialize()
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not payload or len(payload) > MAX_SPOOL_FILE_BYTES:
        raise SpoolValidationError("invalid_payload_size")
    digest = hashlib.sha256(payload).hexdigest()
    target = layout.incoming / f"{digest}.json"
    temporary = layout.incoming / f".{digest}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise SpoolError(f"Cannot publish spool file: {error}") from error
    return target


def claim_spool_file(layout: SpoolLayout) -> SpoolClaim | None:
    layout.initialize()
    with _SPOOL_CLAIM_LOCK:
        candidates = sorted(
            (path for path in layout.incoming.glob("*.json") if path.is_file()),
            key=lambda path: path.name,
        )
        for source in candidates:
            destination = layout.processing / f"{source.stem}.{uuid.uuid4().hex}.json"
            try:
                os.replace(source, destination)
            except FileNotFoundError:
                continue
            except OSError as error:
                raise SpoolError(f"Cannot claim spool file: {error}") from error
            return SpoolClaim(path=destination)
    return None


def archive_spool_claim(layout: SpoolLayout, claim: SpoolClaim) -> Path:
    layout.initialize()
    return _move_claim(claim, layout.archive / claim.path.name)


def quarantine_spool_claim(layout: SpoolLayout, claim: SpoolClaim, *, error_code: str) -> Path:
    layout.initialize()
    _validate_code(error_code, field="spool error code")
    destination = layout.quarantine / f"{claim.path.stem}.{error_code}.json"
    return _move_claim(claim, destination)


def requeue_spool_claim(layout: SpoolLayout, claim: SpoolClaim) -> Path:
    layout.initialize()
    destination = layout.incoming / claim.path.name
    if destination.exists():
        destination = layout.incoming / f"{claim.path.stem}.{uuid.uuid4().hex}.json"
    return _move_claim(claim, destination)


def recover_processing(layout: SpoolLayout) -> int:
    layout.initialize()
    recovered = 0
    for path in sorted(layout.processing.glob("*.json")):
        if not path.is_file():
            continue
        requeue_spool_claim(layout, SpoolClaim(path=path))
        recovered += 1
    return recovered


def process_spool_once(
    layout: SpoolLayout,
    processor: Callable[[bytes], Any],
) -> SpoolProcessResult:
    """Claim one completed file and archive only after the processor returns successfully."""

    claim = claim_spool_file(layout)
    if claim is None:
        return SpoolProcessResult(status="idle")
    try:
        if claim.path.stat().st_size > MAX_SPOOL_FILE_BYTES:
            raise SpoolValidationError("invalid_payload_size")
        payload = claim.path.read_bytes()
        if not payload:
            raise SpoolValidationError("invalid_payload_size")
        processor(payload)
    except SpoolValidationError as error:
        path = quarantine_spool_claim(layout, claim, error_code=error.code)
        return SpoolProcessResult(status="quarantined", path=path, error_code=error.code)
    except Exception:
        requeue_spool_claim(layout, claim)
        raise
    path = archive_spool_claim(layout, claim)
    return SpoolProcessResult(status="archived", path=path)


def _move_claim(claim: SpoolClaim, destination: Path) -> Path:
    if claim.path.parent.resolve() != destination.parent.parent.joinpath("processing").resolve():
        raise SpoolError("Only processing claims can be moved")
    try:
        os.replace(claim.path, destination)
    except OSError as error:
        raise SpoolError(f"Cannot move claimed spool file: {error}") from error
    return destination


def _outbox_id(delivery_key: str) -> str:
    return "po1:" + hashlib.sha256(delivery_key.encode("utf-8")).hexdigest()


def _outbox_from_row(row: sqlite3.Row) -> OutboxRecord:
    status = str(row["status"])
    if status not in OUTBOX_STATUSES:
        raise DeliveryStoreError(f"Unknown outbox status in database: {status!r}")
    payload = json.loads(str(row["payload_json"]))
    if not isinstance(payload, dict):
        raise DeliveryStoreError("Outbox payload must decode to an object")
    return OutboxRecord(
        outbox_id=str(row["outbox_id"]),
        delivery_key=str(row["delivery_key"]),
        action_kind=str(row["action_kind"]),
        payload=payload,
        status=status,
        attempt_count=int(row["attempt_count"]),
        available_at=_time_from_text(str(row["available_at"])),
        expires_at=_time_from_text(str(row["expires_at"])),
        lease_until=_time_from_text(str(row["lease_until"])) if row["lease_until"] else None,
        leased_by=str(row["leased_by"]) if row["leased_by"] else None,
        message_id=str(row["message_id"]) if row["message_id"] else None,
        last_error_code=str(row["last_error_code"]) if row["last_error_code"] else None,
    )


def _canonical_json(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("payload must be a mapping")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _aware(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    return _aware(value, field="timestamp").isoformat(timespec="microseconds")


def _time_from_text(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _aware(parsed, field="database timestamp")


def _require_text(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{field} must be non-empty text up to 512 characters")


def _validate_code(value: str, *, field: str) -> None:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise ValueError(f"{field} must match {_SAFE_CODE.pattern}")
