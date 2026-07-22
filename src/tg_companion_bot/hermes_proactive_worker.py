from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

from .companion_envelope import CompanionEnvelope, EnvelopeValidationError, parse_envelope
from .delivery_outbox import (
    DeliveryStateError,
    DeliveryStoreError,
    OutboxRecord,
    SQLiteDeliveryOutbox,
    SpoolError,
    SpoolLayout,
    recover_processing,
)
from .proactive_pipeline import (
    ProactivePipelineError,
    close_proactive_batch,
    process_proactive_spool_once,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
_PROACTIVE_KINDS = frozenset({"daily_brief", "follow_up_delta", "nightly_attention"})
_ACTION_KEYS = frozenset({"text", "metadata", "reply_markup"})
_METADATA_KEYS = frozenset(
    {"proactive_kind", "task_final", "suppress_completion_feedback"}
)
_AMBIGUOUS_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "read timed",
    "response lost",
)
MAX_ACTION_TEXT_CHARS = 4096


class ProactiveSendAdapter(Protocol):
    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> object: ...


@dataclass(frozen=True)
class HermesProactiveWorkerConfig:
    chat_id: str
    expected_morning_producers: tuple[str, ...] = ("automation", "automation-3")
    poll_interval_seconds: float = 5.0
    morning_barrier_seconds: float = 1500.0
    lease_seconds: float = 60.0
    retry_delay_seconds: float = 60.0
    max_attempts: int = 3
    max_spool_per_cycle: int = 10
    max_batches_per_cycle: int = 10
    max_deliveries_per_cycle: int = 5
    worker_id: str = "hermes-proactive"

    def __post_init__(self) -> None:
        _require_safe_id(self.chat_id, field="chat_id")
        _require_safe_id(self.worker_id, field="worker_id")
        if not isinstance(self.expected_morning_producers, tuple):
            raise ValueError("expected_morning_producers must be a tuple")
        if not 1 <= len(self.expected_morning_producers) <= 16:
            raise ValueError("expected_morning_producers must contain 1 to 16 values")
        if len(set(self.expected_morning_producers)) != len(self.expected_morning_producers):
            raise ValueError("expected_morning_producers must be unique")
        for producer in self.expected_morning_producers:
            _require_safe_id(producer, field="expected_morning_producer")

        _require_bounded_number(
            self.poll_interval_seconds,
            field="poll_interval_seconds",
            minimum=0.01,
            maximum=300.0,
        )
        _require_bounded_number(
            self.morning_barrier_seconds,
            field="morning_barrier_seconds",
            minimum=0.0,
            maximum=86_400.0,
        )
        _require_bounded_number(
            self.lease_seconds,
            field="lease_seconds",
            minimum=1.0,
            maximum=3600.0,
        )
        _require_bounded_number(
            self.retry_delay_seconds,
            field="retry_delay_seconds",
            minimum=0.01,
            maximum=86_400.0,
        )
        _require_bounded_integer(self.max_attempts, field="max_attempts", maximum=20)
        _require_bounded_integer(
            self.max_spool_per_cycle,
            field="max_spool_per_cycle",
            maximum=100,
        )
        _require_bounded_integer(
            self.max_batches_per_cycle,
            field="max_batches_per_cycle",
            maximum=100,
        )
        _require_bounded_integer(
            self.max_deliveries_per_cycle,
            field="max_deliveries_per_cycle",
            maximum=100,
        )


@dataclass(frozen=True)
class WorkerCycleResult:
    recovered_spool_files: int = 0
    archived_spool_files: int = 0
    quarantined_spool_files: int = 0
    spool_errors: int = 0
    batches_closed: int = 0
    batch_errors: int = 0
    deliveries_sent: int = 0
    deliveries_retried: int = 0
    deliveries_uncertain: int = 0
    deliveries_dead_lettered: int = 0
    deliveries_expired: int = 0
    delivery_errors: int = 0

    @property
    def deliveries_processed(self) -> int:
        return (
            self.deliveries_sent
            + self.deliveries_retried
            + self.deliveries_uncertain
            + self.deliveries_dead_lettered
            + self.deliveries_expired
        )


class HermesProactiveWorker:
    """Default-off-ready worker around the phase-0 spool and durable outbox."""

    def __init__(
        self,
        *,
        config: HermesProactiveWorkerConfig,
        layout: SpoolLayout,
        store: SQLiteDeliveryOutbox,
        adapter: ProactiveSendAdapter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.layout = layout
        self.store = store
        self.adapter = adapter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._cycle_lock = asyncio.Lock()
        self._last_error_code: str | None = None
        self._last_cycle_result: WorkerCycleResult | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_error_code(self) -> str | None:
        return self._last_error_code

    @property
    def last_cycle_result(self) -> WorkerCycleResult | None:
        return self._last_cycle_result

    async def start(self) -> bool:
        """Initialize local state and start one idempotent background task."""

        async with self._lifecycle_lock:
            if self.is_running:
                return False
            await asyncio.to_thread(self.layout.initialize)
            await asyncio.to_thread(self.store.initialize)
            self._task = asyncio.create_task(
                self._run_loop(),
                name=f"tg-companion-{self.config.worker_id}",
            )
            return True

    async def stop(self) -> bool:
        """Cancel and await the background task; no adapter disconnect occurs here."""

        async with self._lifecycle_lock:
            task = self._task
            if task is None:
                return False
            self._task = None
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def run_cycle(self) -> WorkerCycleResult:
        """Ingest, close ready batches and drain a bounded number of actions."""

        async with self._cycle_lock:
            await asyncio.to_thread(self.layout.initialize)
            await asyncio.to_thread(self.store.initialize)
            recovered = await asyncio.to_thread(recover_processing, self.layout)
            counters = {
                "recovered_spool_files": recovered,
                "archived_spool_files": 0,
                "quarantined_spool_files": 0,
                "spool_errors": 0,
                "batches_closed": 0,
                "batch_errors": 0,
                "deliveries_sent": 0,
                "deliveries_retried": 0,
                "deliveries_uncertain": 0,
                "deliveries_dead_lettered": 0,
                "deliveries_expired": 0,
                "delivery_errors": 0,
            }

            for _ in range(self.config.max_spool_per_cycle):
                try:
                    result = await asyncio.to_thread(
                        process_proactive_spool_once,
                        self.layout,
                        store=self.store,
                        now=self._now(),
                    )
                except (DeliveryStoreError, ProactivePipelineError, SpoolError, OSError):
                    counters["spool_errors"] += 1
                    break
                if result.status == "idle":
                    break
                if result.status == "archived":
                    counters["archived_spool_files"] += 1
                elif result.status == "quarantined":
                    counters["quarantined_spool_files"] += 1
                else:
                    counters["spool_errors"] += 1

            try:
                batch_keys = await asyncio.to_thread(
                    self.store.open_batch_keys,
                    limit=self.config.max_batches_per_cycle,
                )
            except DeliveryStoreError:
                batch_keys = ()
                counters["batch_errors"] += 1

            for batch_key in batch_keys:
                try:
                    payloads = await asyncio.to_thread(self.store.batch_payloads, batch_key)
                    envelopes = tuple(parse_envelope(payload) for payload in payloads)
                    now = self._now()
                    if not _batch_is_ready(
                        batch_key,
                        envelopes,
                        now=now,
                        expected_producers=self.config.expected_morning_producers,
                        barrier_seconds=self.config.morning_barrier_seconds,
                    ):
                        continue
                    await asyncio.to_thread(
                        close_proactive_batch,
                        batch_key,
                        store=self.store,
                        now=now,
                    )
                    counters["batches_closed"] += 1
                except (
                    DeliveryStoreError,
                    EnvelopeValidationError,
                    ProactivePipelineError,
                    ValueError,
                ):
                    counters["batch_errors"] += 1

            for _ in range(self.config.max_deliveries_per_cycle):
                try:
                    status = await self._deliver_one()
                except (DeliveryStateError, DeliveryStoreError):
                    counters["delivery_errors"] += 1
                    break
                if status == "idle":
                    break
                counter_name = {
                    "sent": "deliveries_sent",
                    "retry": "deliveries_retried",
                    "uncertain": "deliveries_uncertain",
                    "dead_letter": "deliveries_dead_lettered",
                    "expired": "deliveries_expired",
                }.get(status)
                if counter_name is None:
                    counters["delivery_errors"] += 1
                else:
                    counters[counter_name] += 1

            cycle = WorkerCycleResult(**counters)
            self._last_cycle_result = cycle
            self._last_error_code = None
            return cycle

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._last_error_code = "worker_cycle_failed"
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _deliver_one(self) -> str:
        now = self._now()
        record = await asyncio.to_thread(
            self.store.claim_next,
            worker_id=self.config.worker_id,
            now=now,
            lease_seconds=self.config.lease_seconds,
        )
        if record is None:
            return "idle"

        validation_error = _validate_action(record)
        await asyncio.to_thread(
            self.store.begin_send,
            record.outbox_id,
            worker_id=self.config.worker_id,
            now=now,
        )
        if validation_error is not None:
            await asyncio.to_thread(
                self.store.dead_letter,
                record.outbox_id,
                worker_id=self.config.worker_id,
                error_code=validation_error,
                now=now,
            )
            return "dead_letter"

        text = str(record.payload["text"])
        metadata = {
            "proactive_kind": str(record.payload["metadata"]["proactive_kind"]),
            "task_final": False,
            "suppress_completion_feedback": True,
        }
        try:
            adapter_result = await self.adapter.send(
                self.config.chat_id,
                text,
                reply_to=None,
                metadata=metadata,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                asyncio.to_thread(
                    self.store.mark_uncertain,
                    record.outbox_id,
                    worker_id=self.config.worker_id,
                    error_code="send_cancelled",
                    now=self._now(),
                )
            )
            raise
        except ConnectionRefusedError:
            outcome = ("retryable", None, "connection_refused")
        except TimeoutError:
            outcome = ("uncertain", None, "ambiguous_timeout")
        except Exception:
            outcome = ("uncertain", None, "adapter_exception")
        else:
            outcome = _classify_adapter_result(adapter_result)

        outcome_status, message_id, error_code = outcome
        finished_at = self._now()
        if outcome_status == "sent":
            await asyncio.to_thread(
                self.store.acknowledge,
                record.outbox_id,
                worker_id=self.config.worker_id,
                message_id=message_id or "",
                now=finished_at,
            )
            return "sent"
        if outcome_status == "retryable":
            if record.attempt_count >= self.config.max_attempts:
                await asyncio.to_thread(
                    self.store.dead_letter,
                    record.outbox_id,
                    worker_id=self.config.worker_id,
                    error_code="retry_limit_reached",
                    now=finished_at,
                )
                return "dead_letter"
            await asyncio.to_thread(
                self.store.retry,
                record.outbox_id,
                worker_id=self.config.worker_id,
                error_code=error_code or "adapter_retryable",
                available_at=finished_at + timedelta(seconds=self.config.retry_delay_seconds),
                now=finished_at,
            )
            refreshed = await asyncio.to_thread(self.store.get, record.outbox_id)
            return refreshed.status if refreshed is not None else "retry"
        if outcome_status == "uncertain":
            await asyncio.to_thread(
                self.store.mark_uncertain,
                record.outbox_id,
                worker_id=self.config.worker_id,
                error_code=error_code or "ambiguous_delivery",
                now=finished_at,
            )
            return "uncertain"

        await asyncio.to_thread(
            self.store.dead_letter,
            record.outbox_id,
            worker_id=self.config.worker_id,
            error_code=error_code or "adapter_rejected",
            now=finished_at,
        )
        return "dead_letter"

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker clock must return a timezone-aware datetime")
        return value


def _batch_is_ready(
    batch_key: str,
    envelopes: tuple[CompanionEnvelope, ...],
    *,
    now: datetime,
    expected_producers: tuple[str, ...],
    barrier_seconds: float,
) -> bool:
    if not envelopes:
        return False
    if any(envelope.delivery.batch_key != batch_key for envelope in envelopes):
        return False
    not_before = max(envelope.delivery.not_before for envelope in envelopes)
    if now < not_before:
        return False
    kinds = {envelope.run.kind.value for envelope in envelopes}
    if batch_key.startswith("morning:") or "daily_brief" in kinds:
        producers = {envelope.run.producer_id for envelope in envelopes}
        if set(expected_producers).issubset(producers):
            return True
        return now >= not_before + timedelta(seconds=barrier_seconds)
    return kinds.issubset({"follow_up_delta", "nightly_attention"})


def _validate_action(record: OutboxRecord) -> str | None:
    if record.action_kind != "send_message":
        return "invalid_action_kind"
    payload = record.payload
    if set(payload) != _ACTION_KEYS:
        return "invalid_action_shape"
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_ACTION_TEXT_CHARS:
        return "invalid_action_text"
    if any(
        unicodedata.category(character).startswith("C") and character not in "\n\t"
        for character in text
    ):
        return "invalid_action_text"
    if payload.get("reply_markup") is not None:
        return "action_markup_forbidden"
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or set(metadata) != _METADATA_KEYS:
        return "invalid_action_metadata"
    if metadata.get("task_final") is not False:
        return "final_action_forbidden"
    if metadata.get("suppress_completion_feedback") is not True:
        return "completion_feedback_forbidden"
    if metadata.get("proactive_kind") not in _PROACTIVE_KINDS:
        return "invalid_proactive_kind"
    return None


def _classify_adapter_result(result: object) -> tuple[str, str | None, str | None]:
    success = getattr(result, "success", None)
    message_id = getattr(result, "message_id", None)
    retryable = getattr(result, "retryable", None)
    if success is True:
        if message_id is None or not str(message_id).strip():
            return "uncertain", None, "missing_message_id"
        return "sent", str(message_id), None
    if success is not False:
        return "uncertain", None, "invalid_adapter_result"
    if retryable is True:
        return "retryable", None, "adapter_retryable"

    raw_error = getattr(result, "error", "")
    error_text = str(raw_error or "").casefold()
    if any(marker in error_text for marker in _AMBIGUOUS_ERROR_MARKERS):
        return "uncertain", None, "ambiguous_timeout"
    return "permanent", None, "adapter_rejected"


def _require_safe_id(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be a bounded safe identifier")


def _require_bounded_number(
    value: float,
    *,
    field: str,
    minimum: float,
    maximum: float,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    if not minimum <= float(value) <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")


def _require_bounded_integer(value: int, *, field: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field} must be an integer between 1 and {maximum}")
