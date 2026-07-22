from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tg_companion_bot.delivery_outbox import (
    DeliveryCandidate,
    DeliveryStateError,
    EntityRevision,
    IntakeEvent,
    SQLiteDeliveryOutbox,
    SendOutcome,
    SpoolLayout,
    SpoolValidationError,
    claim_spool_file,
    process_spool_once,
    recover_processing,
    run_delivery_step,
    write_spool_atomic,
)
from tg_companion_bot.live_runtime import PendingResult
from tg_companion_bot.runtime_state_store import SQLiteRuntimeStateStore


NOW = datetime(2026, 7, 21, 8, 25, tzinfo=timezone.utc)


def event(
    suffix: str = "1",
    *,
    dedupe_key: str | None = None,
    content_hash: str | None = None,
    batch_key: str | None = "morning:2026-07-21:Europe/Moscow",
) -> IntakeEvent:
    return IntakeEvent(
        envelope_id=f"ce1:{suffix}",
        dedupe_key=dedupe_key or f"automation/run/{suffix}",
        content_hash=content_hash or f"sha256:{suffix}",
        source="automation",
        kind="daily_brief",
        generated_at=NOW,
        payload={"schema_version": 1, "suffix": suffix},
        batch_key=batch_key,
    )


def revision(suffix: str = "1") -> EntityRevision:
    return EntityRevision(
        entity_key="mail:gmail:primary:message-1",
        revision_key=f"revision:{suffix}",
        observed_at=NOW,
        topic_key="mail:gmail:primary:thread-1",
        payload={"title": "Требуется ответ"},
    )


def delivery(suffix: str = "1", *, expires_at: datetime | None = None) -> DeliveryCandidate:
    return DeliveryCandidate(
        delivery_key=f"delivery:{suffix}",
        action_kind="send_message",
        payload={
            "text": "Утренняя сводка",
            "suppress_completion_feedback": True,
            "reply_markup": None,
        },
        expires_at=expires_at or NOW + timedelta(hours=4),
    )


def test_initialize_adds_separate_tables_without_mutating_runtime_state(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    runtime = SQLiteRuntimeStateStore(database)
    with runtime.transaction() as state:
        state.pending_results["101"] = PendingResult("777", "101", "До изменения")
    before_revision = runtime.revision()

    SQLiteDeliveryOutbox(database).initialize()

    assert runtime.revision() == before_revision
    assert runtime.load().pending_results["101"].summary == "До изменения"


def test_ingest_is_transactional_and_deduplicates_envelope_and_delivery(tmp_path: Path) -> None:
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")

    first = store.ingest(
        event(),
        revisions=[revision()],
        deliveries=[delivery()],
        now=NOW,
    )
    duplicate = store.ingest(
        event(),
        revisions=[revision()],
        deliveries=[delivery()],
        now=NOW,
    )
    second_envelope_same_delivery = store.ingest(
        event("2"),
        revisions=[revision()],
        deliveries=[delivery()],
        now=NOW,
    )

    assert first.status == "inserted"
    assert first.inserted_revisions == 1
    assert first.inserted_outbox == 1
    assert duplicate.status == "duplicate"
    assert second_envelope_same_delivery.status == "inserted"
    assert second_envelope_same_delivery.inserted_revisions == 0
    assert second_envelope_same_delivery.inserted_outbox == 0
    assert store.count(table="intake") == 2
    assert store.count(table="revisions") == 1
    assert store.count(table="outbox") == 1


def test_same_envelope_identity_with_changed_hash_is_recorded_as_conflict(tmp_path: Path) -> None:
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    store.ingest(event(content_hash="sha256:first"), now=NOW)

    conflict = store.ingest(event(content_hash="sha256:changed"), now=NOW)

    assert conflict.status == "conflict"
    assert conflict.conflict_reason == "identity_hash_mismatch"
    assert store.count(table="intake") == 1
    assert store.count(table="outbox") == 0


def test_batch_members_are_ordered_and_close_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    store.ingest(event("1"), now=NOW)
    store.ingest(event("2"), now=NOW)

    payloads = store.batch_payloads("morning:2026-07-21:Europe/Moscow")
    assert store.open_batch_keys() == ("morning:2026-07-21:Europe/Moscow",)
    first = store.enqueue_batch(
        batch_key="morning:2026-07-21:Europe/Moscow",
        content_hash="sha256:merged",
        deliveries=[delivery("merged")],
        now=NOW,
    )
    duplicate = store.enqueue_batch(
        batch_key="morning:2026-07-21:Europe/Moscow",
        content_hash="sha256:merged",
        deliveries=[delivery("merged")],
        now=NOW,
    )
    conflict = store.enqueue_batch(
        batch_key="morning:2026-07-21:Europe/Moscow",
        content_hash="sha256:late-change",
        deliveries=[delivery("late")],
        now=NOW,
    )

    assert [payload["suffix"] for payload in payloads] == ["1", "2"]
    assert first.status == "inserted"
    assert first.inserted_outbox == 1
    assert duplicate.status == "duplicate"
    assert conflict.status == "conflict"
    assert conflict.conflict_reason == "batch_content_changed_after_close"
    assert store.count(table="batches") == 1
    assert store.count(table="outbox") == 1
    assert store.open_batch_keys() == ()


def test_outbox_ack_survives_restart_and_cannot_be_acknowledged_twice(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = SQLiteDeliveryOutbox(path)
    result = store.ingest(event(), deliveries=[delivery()], now=NOW)
    record = store.claim_next(worker_id="worker-a", now=NOW, lease_seconds=30)

    assert record is not None
    assert record.attempt_count == 1
    store.begin_send(record.outbox_id, worker_id="worker-a", now=NOW)
    store.acknowledge(
        record.outbox_id,
        worker_id="worker-a",
        message_id="telegram-900",
        now=NOW,
    )

    restarted = SQLiteDeliveryOutbox(path)
    restored = restarted.get(result.outbox_ids[0])
    assert restored is not None
    assert restored.status == "sent"
    assert restored.message_id == "telegram-900"
    assert restarted.claim_next(worker_id="worker-b", now=NOW + timedelta(minutes=1)) is None
    with pytest.raises(DeliveryStateError, match="not being sent"):
        restarted.acknowledge(
            record.outbox_id,
            worker_id="worker-a",
            message_id="telegram-901",
            now=NOW + timedelta(minutes=1),
        )


def test_expired_lease_is_recovered_once_across_competing_workers(tmp_path: Path) -> None:
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    store.ingest(event(), deliveries=[delivery()], now=NOW)
    first = store.claim_next(worker_id="crashed", now=NOW, lease_seconds=10)
    assert first is not None

    def claim(worker_id: str):
        return store.claim_next(
            worker_id=worker_id,
            now=NOW + timedelta(seconds=11),
            lease_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, ("worker-a", "worker-b")))

    active = [record for record in claims if record is not None]
    assert len(active) == 1
    assert active[0].outbox_id == first.outbox_id
    assert active[0].attempt_count == 2
    assert active[0].last_error_code == "lease_expired"


def test_worker_loss_after_send_boundary_becomes_uncertain_without_retry(tmp_path: Path) -> None:
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    store.ingest(event(), deliveries=[delivery()], now=NOW)
    leased = store.claim_next(worker_id="crashed", now=NOW, lease_seconds=10)
    assert leased is not None
    store.begin_send(leased.outbox_id, worker_id="crashed", now=NOW)

    claimed_after_restart = store.claim_next(
        worker_id="restarted",
        now=NOW + timedelta(seconds=11),
        lease_seconds=30,
    )

    assert claimed_after_restart is None
    restored = store.get(leased.outbox_id)
    assert restored is not None
    assert restored.status == "uncertain"
    assert restored.last_error_code == "worker_lost_after_send_started"


def test_fake_sender_step_distinguishes_retry_uncertain_and_permanent(tmp_path: Path) -> None:
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    store.ingest(event("retry"), deliveries=[delivery("retry")], now=NOW)

    retry = run_delivery_step(
        store,
        lambda _: SendOutcome.retryable("connection_refused"),
        worker_id="worker",
        now=NOW,
        retry_delay=timedelta(minutes=5),
    )
    assert retry.resulting_status == "retry"
    assert store.claim_next(worker_id="early", now=NOW + timedelta(minutes=4)) is None

    uncertain = run_delivery_step(
        store,
        lambda _: SendOutcome.uncertain("ambiguous_timeout"),
        worker_id="worker",
        now=NOW + timedelta(minutes=5),
    )
    assert uncertain.resulting_status == "uncertain"
    assert store.count(table="outbox", status="uncertain") == 1

    store.ingest(event("permanent"), deliveries=[delivery("permanent")], now=NOW)
    permanent = run_delivery_step(
        store,
        lambda _: SendOutcome.permanent("permission_denied"),
        worker_id="worker",
        now=NOW,
    )
    assert permanent.resulting_status == "dead_letter"
    assert store.count(table="outbox", status="dead_letter") == 1


def test_unclassified_sender_exception_is_quarantined_as_uncertain(tmp_path: Path) -> None:
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    store.ingest(event(), deliveries=[delivery()], now=NOW)

    def fail(_: object) -> SendOutcome:
        raise RuntimeError("outcome unknown")

    result = run_delivery_step(store, fail, worker_id="worker", now=NOW)

    assert result.resulting_status == "uncertain"
    assert store.count(table="outbox", status="uncertain") == 1


def test_expired_delivery_is_never_claimed(tmp_path: Path) -> None:
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    result = store.ingest(
        event(),
        deliveries=[delivery(expires_at=NOW)],
        now=NOW,
    )

    record = store.get(result.outbox_ids[0])
    assert record is not None
    assert record.status == "expired"
    assert store.claim_next(worker_id="worker", now=NOW) is None


def test_atomic_spool_ignores_tmp_archives_success_and_quarantines_safe_error(
    tmp_path: Path,
) -> None:
    layout = SpoolLayout(tmp_path / "spool")
    layout.initialize()
    (layout.incoming / ".partial.tmp").write_bytes(b"partial")
    published = write_spool_atomic(layout, b'{"schema_version":1}')

    seen: list[bytes] = []
    processed = process_spool_once(layout, lambda payload: seen.append(payload))

    assert published.exists() is False
    assert processed.status == "archived"
    assert processed.path is not None and processed.path.parent == layout.archive
    assert seen == [b'{"schema_version":1}']
    assert (layout.incoming / ".partial.tmp").exists()

    write_spool_atomic(layout, b'{"schema_version":999}')

    def reject(_: bytes) -> None:
        raise SpoolValidationError("unsupported_schema")

    quarantined = process_spool_once(layout, reject)
    assert quarantined.status == "quarantined"
    assert quarantined.error_code == "unsupported_schema"
    assert quarantined.path is not None
    assert quarantined.path.parent == layout.quarantine
    assert "unsupported_schema" in quarantined.path.name
    assert "schema_version" not in quarantined.path.name


def test_spool_processor_failure_requeues_and_processing_recovery_is_restart_safe(
    tmp_path: Path,
) -> None:
    layout = SpoolLayout(tmp_path / "spool")
    write_spool_atomic(layout, b'{"schema_version":1}')

    with pytest.raises(RuntimeError, match="database unavailable"):
        process_spool_once(layout, lambda _: (_ for _ in ()).throw(RuntimeError("database unavailable")))

    assert list(layout.incoming.glob("*.json"))
    claim = claim_spool_file(layout)
    assert claim is not None
    assert list(layout.processing.glob("*.json"))
    assert recover_processing(layout) == 1
    assert not list(layout.processing.glob("*.json"))
    assert list(layout.incoming.glob("*.json"))


def test_competing_spool_claims_receive_distinct_completed_files(tmp_path: Path) -> None:
    layout = SpoolLayout(tmp_path / "spool")
    write_spool_atomic(layout, b'{"envelope":1}')
    write_spool_atomic(layout, b'{"envelope":2}')

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: claim_spool_file(layout), range(2)))

    assert all(claim is not None for claim in claims)
    paths = {claim.path for claim in claims if claim is not None}
    assert len(paths) == 2
    assert not list(layout.incoming.glob("*.json"))
