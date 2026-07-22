from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tg_companion_bot.delivery_outbox import (
    DeliveryCandidate,
    IntakeEvent,
    SQLiteDeliveryOutbox,
    SpoolLayout,
    claim_spool_file,
    write_spool_atomic,
)
from tg_companion_bot.hermes_proactive_worker import (
    HermesProactiveWorker,
    HermesProactiveWorkerConfig,
)


NOW = datetime.fromisoformat("2026-07-21T08:20:00+03:00")
MORNING_BATCH = "morning:2026-07-21:Europe/Moscow"


def _digest(character: str) -> str:
    return character * 64


@dataclass
class FakeSendResult:
    success: bool
    message_id: str | None = None
    error: str | None = None
    retryable: bool = False


class FakeAdapter:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[dict] = []

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.calls.append(
            {
                "chat_id": chat_id,
                "content": content,
                "reply_to": reply_to,
                "metadata": metadata,
            }
        )
        outcome = self.outcomes.pop(0) if self.outcomes else FakeSendResult(True, "message-1")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


def _item(ordinal: int, *, title: str = "Ответить клиенту") -> dict:
    character = format((ordinal % 15) + 1, "x")
    return {
        "item_id": f"ci1:{_digest(character)}",
        "entity_key": "mail:gmail:primary:message-1",
        "topic_key": "mail:gmail:primary:thread-1",
        "revision_key": f"sha256:{_digest(character)}",
        "section": "mail",
        "source_id": "gmail:primary",
        "change": "new",
        "severity": "high",
        "urgency_bucket": "none",
        "observed_at": "2026-07-21T08:02:00+03:00",
        "occurred_at": None,
        "due_at": None,
        "title": title,
        "summary": "Краткое описание",
        "recommended_action": "Проверить и решить",
        "facts": {"status": "open", "ordinal": ordinal},
        "changes": [],
        "provenance": [{"producer_id": "automation", "source_id": "gmail:primary"}],
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
    producer_id: str,
    kind: str = "daily_brief",
    batch_key: str = MORNING_BATCH,
    items: list[dict] | None = None,
    not_before: str = "2026-07-21T08:00:00+03:00",
) -> dict:
    character = format((ordinal % 15) + 1, "x")
    completed_minute = 4 + ordinal
    completed_at = f"2026-07-21T08:{completed_minute:02d}:00+03:00"
    return {
        "schema": "tg-companion/envelope",
        "schema_version": 1,
        "envelope_id": f"ce1:{_digest(character)}",
        "run": {
            "producer": "codex_automation",
            "producer_id": producer_id,
            "kind": kind,
            "run_id": f"{producer_id}/2026-07-21T05:00:00Z",
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
            "not_before": not_before,
            "expires_at": "2026-07-21T12:00:00+03:00",
        },
    }


def _publish(layout: SpoolLayout, payload: dict) -> None:
    write_spool_atomic(
        layout,
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    )


def _config(**overrides) -> HermesProactiveWorkerConfig:
    values = {
        "chat_id": "trusted-chat-777",
        "expected_morning_producers": ("automation", "automation-3"),
        "poll_interval_seconds": 0.01,
        "max_deliveries_per_cycle": 10,
    }
    values.update(overrides)
    return HermesProactiveWorkerConfig(**values)


def _worker(
    tmp_path: Path,
    *,
    adapter: FakeAdapter | None = None,
    clock: MutableClock | None = None,
    config: HermesProactiveWorkerConfig | None = None,
) -> tuple[HermesProactiveWorker, SpoolLayout, SQLiteDeliveryOutbox, FakeAdapter, MutableClock]:
    layout = SpoolLayout(tmp_path / "spool")
    store = SQLiteDeliveryOutbox(tmp_path / "runtime.sqlite3")
    fake_adapter = adapter or FakeAdapter()
    fake_clock = clock or MutableClock(NOW)
    worker = HermesProactiveWorker(
        config=config or _config(),
        layout=layout,
        store=store,
        adapter=fake_adapter,
        clock=fake_clock,
    )
    return worker, layout, store, fake_adapter, fake_clock


def _valid_action(text: str = "Утренняя сводка") -> dict:
    return {
        "text": text,
        "metadata": {
            "proactive_kind": "daily_brief",
            "task_final": False,
            "suppress_completion_feedback": True,
        },
        "reply_markup": None,
    }


def _seed_actions(
    store: SQLiteDeliveryOutbox,
    actions: list[dict],
    *,
    now: datetime = NOW,
) -> tuple[str, ...]:
    event = IntakeEvent(
        envelope_id=f"manual:{len(actions)}:{now.isoformat()}",
        dedupe_key=f"manual-dedupe:{len(actions)}:{now.isoformat()}",
        content_hash="sha256:manual",
        source="test",
        kind="daily_brief",
        generated_at=now,
        payload={"test": True},
    )
    result = store.ingest(
        event,
        deliveries=[
            DeliveryCandidate(
                delivery_key=f"manual-delivery:{index}:{now.isoformat()}",
                action_kind="send_message",
                payload=payload,
                available_at=now,
                expires_at=now + timedelta(hours=2),
            )
            for index, payload in enumerate(actions)
        ],
        now=now,
    )
    return result.outbox_ids


def test_two_morning_members_close_once_and_send_to_only_trusted_chat(tmp_path: Path) -> None:
    worker, layout, store, adapter, _ = _worker(tmp_path)
    _publish(layout, _envelope(1, producer_id="automation", items=[_item(1, title="Старый текст")]))
    _publish(layout, _envelope(2, producer_id="automation-3", items=[_item(2)]))

    result = asyncio.run(worker.run_cycle())

    assert result.archived_spool_files == 2
    assert result.batches_closed == 1
    assert result.deliveries_sent == 1
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["chat_id"] == "trusted-chat-777"
    assert adapter.calls[0]["reply_to"] is None
    assert adapter.calls[0]["metadata"]["suppress_completion_feedback"] is True
    assert adapter.calls[0]["metadata"]["task_final"] is False
    assert "Ответить клиенту" in adapter.calls[0]["content"]
    assert store.count(table="outbox", status="sent") == 1
    assert asyncio.run(worker.run_cycle()).deliveries_processed == 0
    assert len(adapter.calls) == 1


def test_morning_waits_for_barrier_when_expected_member_is_missing(tmp_path: Path) -> None:
    worker, layout, store, adapter, clock = _worker(tmp_path)
    _publish(layout, _envelope(1, producer_id="automation", items=[_item(1)]))

    before = asyncio.run(worker.run_cycle())
    assert before.batches_closed == 0
    assert not adapter.calls
    assert store.open_batch_keys() == (MORNING_BATCH,)

    clock.advance(minutes=6)
    after = asyncio.run(worker.run_cycle())
    assert after.batches_closed == 1
    assert after.deliveries_sent == 1
    assert len(adapter.calls) == 1


def test_empty_delta_closes_immediately_without_outbox_send(tmp_path: Path) -> None:
    worker, layout, store, adapter, _ = _worker(tmp_path)
    delta_batch = "delta:2026-07-21T08:15:00+03:00"
    _publish(
        layout,
        _envelope(
            3,
            producer_id="automation-3",
            kind="follow_up_delta",
            batch_key=delta_batch,
            items=[],
        ),
    )

    result = asyncio.run(worker.run_cycle())

    assert result.batches_closed == 1
    assert result.deliveries_processed == 0
    assert not adapter.calls
    assert store.count(table="batches") == 1
    assert store.count(table="outbox") == 0


def test_delta_waits_until_not_before_even_though_no_morning_barrier_applies(tmp_path: Path) -> None:
    worker, layout, store, adapter, clock = _worker(tmp_path)
    delta_batch = "delta:2026-07-21T09:00:00+03:00"
    _publish(
        layout,
        _envelope(
            5,
            producer_id="automation-3",
            kind="follow_up_delta",
            batch_key=delta_batch,
            items=[_item(5, title="Будущая дельта")],
            not_before="2026-07-21T09:00:00+03:00",
        ),
    )

    before = asyncio.run(worker.run_cycle())
    assert before.batches_closed == 0
    assert not adapter.calls
    assert store.open_batch_keys() == (delta_batch,)

    clock.advance(minutes=41)
    after = asyncio.run(worker.run_cycle())
    assert after.batches_closed == 1
    assert after.deliveries_sent == 1
    assert len(adapter.calls) == 1


def test_morning_barrier_uses_latest_member_not_before(tmp_path: Path) -> None:
    config = _config(
        expected_morning_producers=("automation", "automation-3", "automation-4")
    )
    clock = MutableClock(datetime.fromisoformat("2026-07-21T08:30:00+03:00"))
    worker, layout, store, adapter, _ = _worker(tmp_path, config=config, clock=clock)
    _publish(layout, _envelope(1, producer_id="automation", items=[_item(1)]))
    _publish(
        layout,
        _envelope(
            2,
            producer_id="automation-3",
            items=[_item(2)],
            not_before="2026-07-21T08:10:00+03:00",
        ),
    )

    before = asyncio.run(worker.run_cycle())
    assert before.batches_closed == 0
    assert not adapter.calls
    assert store.open_batch_keys() == (MORNING_BATCH,)

    clock.advance(minutes=6)
    after = asyncio.run(worker.run_cycle())
    assert after.batches_closed == 1
    assert after.deliveries_sent == 1
    assert len(adapter.calls) == 1


def test_invalid_markup_or_payload_chat_override_is_dead_lettered_without_send(tmp_path: Path) -> None:
    worker, _, store, adapter, _ = _worker(tmp_path)
    markup = {**_valid_action(), "reply_markup": {"inline_keyboard": [[{"text": "Да"}]]}}
    override = {**_valid_action(), "chat_id": "attacker-chat"}
    _seed_actions(store, [markup, override])

    result = asyncio.run(worker.run_cycle())

    assert result.deliveries_dead_lettered == 2
    assert store.count(table="outbox", status="dead_letter") == 2
    assert not adapter.calls


def test_explicit_retryable_failure_retries_but_timeout_becomes_uncertain(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            FakeSendResult(False, error="Not connected", retryable=True),
            TimeoutError("response may have been delivered"),
        ]
    )
    worker, _, store, _, _ = _worker(tmp_path, adapter=adapter)
    outbox_ids = _seed_actions(store, [_valid_action("Первое"), _valid_action("Второе")])

    result = asyncio.run(worker.run_cycle())

    assert result.deliveries_retried == 1
    assert result.deliveries_uncertain == 1
    statuses = {store.get(outbox_id).status for outbox_id in outbox_ids}
    assert statuses == {"retry", "uncertain"}
    error_codes = {store.get(outbox_id).last_error_code for outbox_id in outbox_ids}
    assert error_codes == {"adapter_retryable", "ambiguous_timeout"}
    assert len(adapter.calls) == 2


def test_nonretryable_not_connected_is_permanent_but_timeout_text_is_uncertain(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(
        [
            FakeSendResult(False, error="Not connected", retryable=False),
            FakeSendResult(False, error="Read timeout after request", retryable=False),
        ]
    )
    worker, _, store, _, _ = _worker(tmp_path, adapter=adapter)
    outbox_ids = _seed_actions(store, [_valid_action("Первое"), _valid_action("Второе")])

    result = asyncio.run(worker.run_cycle())

    assert result.deliveries_dead_lettered == 1
    assert result.deliveries_uncertain == 1
    statuses = {store.get(outbox_id).status for outbox_id in outbox_ids}
    assert statuses == {"dead_letter", "uncertain"}
    error_codes = {store.get(outbox_id).last_error_code for outbox_id in outbox_ids}
    assert error_codes == {"adapter_rejected", "ambiguous_timeout"}


def test_processing_claim_is_recovered_after_restart_and_delivered(tmp_path: Path) -> None:
    worker, layout, store, adapter, _ = _worker(tmp_path)
    delta_batch = "delta:2026-07-21T08:15:00+03:00"
    _publish(
        layout,
        _envelope(
            4,
            producer_id="automation-3",
            kind="follow_up_delta",
            batch_key=delta_batch,
            items=[_item(4, title="Изменение после рестарта")],
        ),
    )
    claimed = claim_spool_file(layout)
    assert claimed is not None and claimed.path.parent == layout.processing

    result = asyncio.run(worker.run_cycle())

    assert result.recovered_spool_files == 1
    assert result.archived_spool_files == 1
    assert result.deliveries_sent == 1
    assert len(adapter.calls) == 1
    assert "Изменение после рестарта" in adapter.calls[0]["content"]
    assert store.count(table="outbox", status="sent") == 1


def test_start_and_stop_are_idempotent_and_do_not_manage_adapter_connection(tmp_path: Path) -> None:
    worker, _, _, adapter, _ = _worker(tmp_path)

    async def scenario() -> None:
        assert await worker.start() is True
        assert worker.is_running is True
        assert await worker.start() is False
        await asyncio.sleep(0.025)
        assert await worker.stop() is True
        assert worker.is_running is False
        assert await worker.stop() is False

    asyncio.run(scenario())

    assert not adapter.calls


def test_config_rejects_untrusted_or_unbounded_values() -> None:
    with pytest.raises(ValueError, match="chat_id"):
        _config(chat_id="bad\nchat")
    with pytest.raises(ValueError, match="unique"):
        _config(expected_morning_producers=("automation", "automation"))
    with pytest.raises(ValueError, match="max_deliveries"):
        _config(max_deliveries_per_cycle=0)
    with pytest.raises(ValueError, match="morning_barrier"):
        _config(morning_barrier_seconds=100_000)
