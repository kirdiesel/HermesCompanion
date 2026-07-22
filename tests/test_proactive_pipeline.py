from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from tg_companion_bot.delivery_outbox import (
    SQLiteDeliveryOutbox,
    SendOutcome,
    SpoolLayout,
    run_delivery_step,
    write_spool_atomic,
)
from tg_companion_bot.proactive_pipeline import (
    close_proactive_batch,
    process_proactive_spool_once,
)


NOW = datetime.fromisoformat("2026-07-21T08:20:00+03:00")
MORNING_BATCH = "morning:2026-07-21:Europe/Moscow"


def _digest(character: str) -> str:
    return character * 64


def _item(
    ordinal: int,
    *,
    title: str,
    observed_at: str,
    section: str = "mail",
    entity_key: str = "mail:gmail:primary:message-1",
    topic_key: str | None = "mail:gmail:primary:thread-1",
    source_id: str = "gmail:primary",
) -> dict:
    character = format((ordinal % 15) + 1, "x")
    return {
        "item_id": f"ci1:{_digest(character)}",
        "entity_key": entity_key,
        "topic_key": topic_key,
        "revision_key": f"sha256:{_digest(character)}",
        "section": section,
        "source_id": source_id,
        "change": "new",
        "severity": "high" if section == "mail" else "normal",
        "urgency_bucket": "none",
        "observed_at": observed_at,
        "occurred_at": None,
        "due_at": None,
        "title": title,
        "summary": "Краткое описание; подробнее: https://tracking.example/item/1",
        "recommended_action": "Проверить и решить",
        "facts": {"status": "open", "ordinal": ordinal},
        "changes": [],
        "provenance": [{"producer_id": "automation", "source_id": source_id}],
        "trust": {
            "content": "external_untrusted",
            "identity": "managed_connector",
            "completeness": "complete",
            "action_policy": "proposal_only",
            "prompt_injection_suspected": False,
        },
        "expires_at": "2026-07-22T12:00:00+03:00",
    }


def _envelope(
    ordinal: int,
    *,
    kind: str = "daily_brief",
    items: list[dict] | None = None,
    completed_at: str = "2026-07-21T08:05:00+03:00",
    batch_key: str = MORNING_BATCH,
) -> dict:
    character = format((ordinal % 15) + 1, "x")
    return {
        "schema": "tg-companion/envelope",
        "schema_version": 1,
        "envelope_id": f"ce1:{_digest(character)}",
        "run": {
            "producer": "codex_automation",
            "producer_id": f"automation-{ordinal}",
            "kind": kind,
            "run_id": f"automation-{ordinal}/2026-07-21T05:00:00Z",
            "attempt": 1,
            "scheduled_for": "2026-07-21T08:00:00+03:00",
            "started_at": "2026-07-21T08:00:01+03:00",
            "completed_at": completed_at,
            "timezone": "Europe/Moscow",
        },
        "window": {
            "from": "2026-07-20T08:00:00+03:00",
            "to": completed_at,
            "calendar_horizon_to": "2026-08-20T08:00:00+03:00",
        },
        "cursor": {
            "before": f"sha256:{_digest('a')}",
            "after": f"sha256:{_digest('b')}",
            "complete": True,
        },
        "coverage": [
            {
                "source_id": "gmail:primary",
                "source_type": "gmail",
                "status": "ok",
                "checked_at": completed_at,
                "cursor_before": "previous",
                "cursor_after": "current",
                "error_code": None,
            }
        ],
        "items": items or [],
        "delivery": {
            "batch_key": batch_key,
            "not_before": "2026-07-21T08:00:00+03:00",
            "expires_at": "2026-07-21T12:00:00+03:00",
        },
    }


def _bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def test_two_atomic_envelopes_merge_to_one_durable_action_and_fake_ack(tmp_path: Path) -> None:
    layout = SpoolLayout(tmp_path / "spool")
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    first = _envelope(
        1,
        items=[
            _item(
                1,
                title="Старое название вопроса",
                observed_at="2026-07-21T08:02:00+03:00",
            )
        ],
    )
    second = _envelope(
        2,
        completed_at="2026-07-21T08:16:00+03:00",
        items=[
            _item(
                2,
                title="Ответить клиенту",
                observed_at="2026-07-21T08:15:00+03:00",
            ),
            _item(
                3,
                title="Проверить встречу",
                observed_at="2026-07-21T08:14:00+03:00",
                section="calendar",
                entity_key="calendar:gcal:primary:event-1",
                topic_key=None,
                source_id="gcal:primary",
            ),
        ],
    )
    write_spool_atomic(layout, _bytes(first))
    write_spool_atomic(layout, _bytes(second))

    assert process_proactive_spool_once(layout, store=store, now=NOW).status == "archived"
    assert process_proactive_spool_once(layout, store=store, now=NOW).status == "archived"
    closed = close_proactive_batch(MORNING_BATCH, store=store, now=NOW)

    assert closed.status == "inserted"
    assert closed.inserted_outbox == 1
    assert store.count(table="intake") == 2
    assert store.count(table="revisions") == 3
    assert store.count(table="outbox") == 1
    record = store.get(closed.outbox_ids[0])
    assert record is not None
    assert record.payload["reply_markup"] is None
    assert record.payload["metadata"]["suppress_completion_feedback"] is True
    assert "Ответить клиенту" in record.payload["text"]
    assert "Старое название вопроса" not in record.payload["text"]
    assert "Проверить встречу" in record.payload["text"]
    assert "tracking.example" not in record.payload["text"]

    step = run_delivery_step(
        store,
        lambda _: SendOutcome.sent("telegram-1001"),
        worker_id="fake-worker",
        now=NOW,
    )
    assert step.resulting_status == "sent"
    sent = store.get(closed.outbox_ids[0])
    assert sent is not None and sent.message_id == "telegram-1001"


def test_replayed_spool_and_batch_close_do_not_duplicate_delivery(tmp_path: Path) -> None:
    layout = SpoolLayout(tmp_path / "spool")
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    payload = _bytes(
        _envelope(
            1,
            items=[
                _item(
                    1,
                    title="Ответить клиенту",
                    observed_at="2026-07-21T08:02:00+03:00",
                )
            ],
        )
    )
    write_spool_atomic(layout, payload)
    process_proactive_spool_once(layout, store=store, now=NOW)
    first = close_proactive_batch(MORNING_BATCH, store=store, now=NOW)

    write_spool_atomic(layout, payload)
    replay = process_proactive_spool_once(layout, store=store, now=NOW)
    duplicate_close = close_proactive_batch(MORNING_BATCH, store=store, now=NOW)

    assert replay.status == "archived"
    assert first.inserted_outbox == 1
    assert duplicate_close.status == "duplicate"
    assert store.count(table="intake") == 1
    assert store.count(table="outbox") == 1


def test_invalid_spool_payload_is_quarantined_without_raw_content_in_name(tmp_path: Path) -> None:
    layout = SpoolLayout(tmp_path / "spool")
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    write_spool_atomic(layout, b'{"schema":"contains-secret-but-invalid"}')

    result = process_proactive_spool_once(layout, store=store, now=NOW)

    assert result.status == "quarantined"
    assert result.error_code == "invalid_schema"
    assert result.path is not None
    assert "contains-secret" not in result.path.name
    assert store.count(table="intake") == 0


def test_empty_delta_closes_as_durable_noop_without_outbox_row(tmp_path: Path) -> None:
    layout = SpoolLayout(tmp_path / "spool")
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    batch_key = "delta:2026-07-21T12:15:00+03:00"
    payload = _bytes(
        _envelope(
            4,
            kind="follow_up_delta",
            items=[],
            completed_at="2026-07-21T12:16:00+03:00",
            batch_key=batch_key,
        )
    )
    # Keep delivery viable at the supplied deterministic test clock.
    decoded = json.loads(payload)
    decoded["run"]["scheduled_for"] = "2026-07-21T12:15:00+03:00"
    decoded["run"]["started_at"] = "2026-07-21T12:15:01+03:00"
    decoded["window"]["to"] = "2026-07-21T12:16:00+03:00"
    decoded["delivery"]["not_before"] = "2026-07-21T12:15:00+03:00"
    decoded["delivery"]["expires_at"] = "2026-07-22T12:15:00+03:00"
    payload = _bytes(decoded)
    delta_now = datetime.fromisoformat("2026-07-21T12:17:00+03:00")
    write_spool_atomic(layout, payload)

    process_proactive_spool_once(layout, store=store, now=delta_now)
    closed = close_proactive_batch(batch_key, store=store, now=delta_now)

    assert closed.status == "inserted"
    assert closed.inserted_outbox == 0
    assert store.count(table="batches") == 1
    assert store.count(table="outbox") == 0
