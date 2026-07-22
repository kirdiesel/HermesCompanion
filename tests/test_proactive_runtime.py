from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from tg_companion_bot.companion_envelope import parse_envelope
from tg_companion_bot.proactive_runtime import (
    merge_proactive_envelopes,
    plan_proactive_delivery,
)


NOW = datetime.fromisoformat("2026-07-21T08:20:00+03:00")


def _digest(character: str) -> str:
    return character * 64


def _item(
    ordinal: int,
    *,
    entity_key: str | None = None,
    topic_key: str | None = None,
    revision: str | None = None,
    section: str = "mail",
    change: str = "new",
    severity: str = "normal",
    observed_at: str = "2026-07-21T08:02:00+03:00",
    due_at: str | None = None,
    title: str | None = None,
    summary: str = "Краткое описание",
    source_id: str | None = None,
) -> dict:
    hex_character = format((ordinal % 15) + 1, "x")
    source_id = source_id or {
        "mail": "gmail:primary",
        "calendar": "gcal:primary",
        "follow_up": "derived:follow-up",
        "nightly": "nightly:local",
    }[section]
    entity_key = entity_key or {
        "mail": f"mail:gmail:primary:message-{ordinal}",
        "calendar": f"calendar:gcal:primary:event-{ordinal}",
        "follow_up": f"follow-up:topic-{ordinal}",
        "nightly": f"nightly:attention-{ordinal}",
    }[section]
    return {
        "item_id": f"ci1:{_digest(hex_character)}",
        "entity_key": entity_key,
        "topic_key": topic_key,
        "revision_key": revision or f"sha256:{_digest(hex_character)}",
        "section": section,
        "source_id": source_id,
        "change": change,
        "severity": severity,
        "urgency_bucket": "within_24h" if due_at else "none",
        "observed_at": observed_at,
        "occurred_at": None,
        "due_at": due_at,
        "title": title or f"Пункт {ordinal}",
        "summary": summary,
        "recommended_action": "Проверить и решить",
        "facts": {"status": "open", "ordinal": ordinal},
        "changes": [],
        "provenance": [{"producer_id": "automation", "source_id": source_id}],
        "trust": {
            "content": "external_untrusted" if section in {"mail", "calendar", "follow_up"} else "local_untrusted",
            "identity": "managed_connector" if section != "nightly" else "local_report",
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
    coverage: list[dict] | None = None,
    completed_at: str = "2026-07-21T08:05:00+03:00",
    batch_key: str | None = None,
):
    hex_character = format((ordinal % 15) + 1, "x")
    payload = {
        "schema": "tg-companion/envelope",
        "schema_version": 1,
        "envelope_id": f"ce1:{_digest(hex_character)}",
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
        "coverage": coverage
        if coverage is not None
        else [
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
            "batch_key": batch_key
            or ("morning:2026-07-21:Europe/Moscow" if kind == "daily_brief" else "delta:2026-07-21T08:00+03:00"),
            "not_before": "2026-07-21T08:00:00+03:00",
            "expires_at": "2026-07-22T12:00:00+03:00",
        },
    }
    return parse_envelope(payload)


def test_two_morning_envelopes_merge_exact_identity_once_without_fuzzy_title_dedupe():
    common = {
        "entity_key": "mail:gmail:primary:message-shared",
        "revision": f"sha256:{_digest('c')}",
        "title": "Совпадающее письмо",
    }
    first = _envelope(1, items=[_item(1, **common)])
    second = _envelope(
        2,
        completed_at="2026-07-21T08:15:00+03:00",
        items=[
            _item(2, observed_at="2026-07-21T08:12:00+03:00", summary="Более свежая формулировка", **common),
            _item(3, entity_key="mail:gmail:primary:message-distinct", title="Совпадающее письмо"),
        ],
    )

    batch = merge_proactive_envelopes([second, first], now=NOW)

    assert len(batch.items) == 2
    shared = next(item for item in batch.items if item.identity_key.endswith("message-shared"))
    assert shared.summary == "Более свежая формулировка"
    assert sum("Совпадающее письмо" == item.title for item in batch.items) == 2


def test_newest_exact_revision_replaces_old_revision_for_same_entity():
    old = _item(
        1,
        entity_key="calendar:gcal:primary:event-1",
        revision=f"sha256:{_digest('a')}",
        section="calendar",
        observed_at="2026-07-21T08:01:00+03:00",
        title="Встреча в 13:00",
    )
    changed = _item(
        2,
        entity_key="calendar:gcal:primary:event-1",
        revision=f"sha256:{_digest('b')}",
        section="calendar",
        change="changed",
        observed_at="2026-07-21T08:10:00+03:00",
        title="Встреча перенесена на 14:00",
    )

    batch = merge_proactive_envelopes(
        [_envelope(1, items=[old]), _envelope(2, items=[changed], completed_at="2026-07-21T08:12:00+03:00")],
        now=NOW,
    )

    assert len(batch.items) == 1
    assert batch.items[0].revision_key == f"sha256:{_digest('b')}"
    assert batch.items[0].title == "Встреча перенесена на 14:00"


def test_empty_daytime_delta_is_a_noop():
    envelope = _envelope(3, kind="follow_up_delta", items=[])

    assert plan_proactive_delivery([envelope], now=NOW) is None


def test_partial_yandex_warning_is_rendered_once_and_has_no_buttons():
    coverage = [
        {
            "source_id": "yandex:primary",
            "source_type": "yandex",
            "status": "partial",
            "checked_at": "2026-07-21T08:04:00+03:00",
            "cursor_before": "previous",
            "cursor_after": "previous",
            "error_code": "browser_unavailable",
        }
    ]
    first = _envelope(4, kind="follow_up_delta", coverage=coverage)
    coverage[0] = {**coverage[0], "checked_at": "2026-07-21T08:14:00+03:00"}
    second = _envelope(5, kind="follow_up_delta", coverage=coverage, completed_at="2026-07-21T08:15:00+03:00")

    action = plan_proactive_delivery([first, second], now=NOW)

    assert action is not None
    assert action.text.count("Яндекс Почта") == 1
    assert "не полностью" in action.text
    assert action.reply_markup is None
    assert action.metadata["suppress_completion_feedback"] is True
    assert action.metadata["task_final"] is False


def test_sections_and_priority_are_stable_and_noise_budget_keeps_all_critical():
    items = [
        _item(1, section="nightly", severity="critical", title="Критичный ночной"),
        _item(2, section="mail", severity="critical", title="Критичное письмо"),
        _item(3, section="calendar", severity="high", due_at="2026-07-21T09:00:00+03:00", title="Срочный календарь"),
        _item(4, section="follow_up", severity="high", due_at="2026-07-21T10:00:00+03:00", title="Срочное действие"),
        _item(5, section="mail", severity="normal", title="Обычное письмо"),
        _item(6, section="calendar", severity="normal", title="Обычное событие"),
        _item(7, section="follow_up", severity="normal", title="Обычное действие"),
        _item(8, section="mail", severity="low", title="Низкий приоритет 1"),
        _item(9, section="mail", severity="low", title="Низкий приоритет 2"),
    ]
    envelope = _envelope(6, items=items)

    forward = plan_proactive_delivery([envelope], now=NOW)
    reverse = plan_proactive_delivery([replace(envelope, items=tuple(reversed(envelope.items)))], now=NOW)

    assert forward is not None and reverse is not None
    assert forward.text == reverse.text
    assert forward.text.index("Почта") < forward.text.index("Календарь")
    assert forward.text.index("Календарь") < forward.text.index("Дальнейшие действия")
    assert forward.text.index("Дальнейшие действия") < forward.text.index("Ночной разбор")
    assert "Критичное письмо" in forward.text
    assert "Вопросов для разбора — 1, из них срочных — 1" in forward.text
    assert "Критичный ночной" not in forward.text
    assert "Низкий приоритет 1" not in forward.text
    assert "Низкий приоритет 2" not in forward.text
    assert "Ещё 2 менее срочных" in forward.text


def test_renderer_defensively_removes_html_and_raw_tracking_urls():
    envelope = _envelope(7, items=[_item(1)])
    unsafe_item = replace(
        envelope.items[0],
        title="<b>Важное письмо</b>",
        summary="Открыть https://tracker.example/path?id=secret и проверить.",
    )
    envelope = replace(envelope, items=(unsafe_item,))

    action = plan_proactive_delivery([envelope], now=NOW)

    assert action is not None
    assert "Важное письмо" in action.text
    assert "<b>" not in action.text
    assert "https://" not in action.text
    assert "tracker.example" not in action.text
    assert "[ссылка скрыта]" in action.text


def test_empty_morning_brief_is_informational_not_a_delta_noop():
    action = plan_proactive_delivery([_envelope(8, items=[])], now=NOW)

    assert action is not None
    assert "Утренняя сводка" in action.text
    assert "Срочного и требующего решения нет" in action.text
    assert action.reply_markup is None
