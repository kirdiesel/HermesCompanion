from __future__ import annotations

from copy import deepcopy
import json

import pytest

from tg_companion_bot.companion_envelope import (
    MAX_ENVELOPE_BYTES,
    CompanionEnvelope,
    EnvelopeKind,
    EnvelopeValidationError,
    Section,
    canonical_hash,
    compute_delivery_key,
    compute_envelope_id,
    compute_item_id,
    compute_revision_key,
    parse_envelope,
    parse_envelope_bytes,
)


def _item(*, section: str = "mail", source_id: str = "gmail:primary") -> dict:
    content = "local_untrusted" if section == "nightly" else "external_untrusted"
    identity = "local_report" if section == "nightly" else "managed_connector"
    entity_key = "nightly:attention-2026-w30" if section == "nightly" else "mail:gmail:primary:message-42"
    item = {
        "item_id": compute_item_id(entity_key),
        "entity_key": entity_key,
        "topic_key": None,
        "revision_key": "sha256:" + "2" * 64,
        "section": section,
        "source_id": source_id,
        "change": "new",
        "severity": "high",
        "urgency_bucket": "within_24h",
        "observed_at": "2026-07-21T08:01:30+03:00",
        "occurred_at": None,
        "due_at": "2026-07-21T18:00:00+03:00",
        "title": "Нужно ответить сегодня",
        "summary": "Получено важное сообщение с подтверждённым сроком.",
        "recommended_action": "Подготовить ответ.",
        "facts": {"message_id": "message-42", "status": "needs_reply"},
        "changes": [
            {"field": "status", "before": "new", "after": "needs_reply"},
            {"field": "due_at", "before": None, "after": "2026-07-21T18:00:00+03:00"},
        ],
        "provenance": [{"producer_id": "automation", "source_id": source_id}],
        "trust": {
            "content": content,
            "identity": identity,
            "completeness": "complete",
            "action_policy": "proposal_only",
            "prompt_injection_suspected": False,
        },
        "expires_at": "2026-07-22T08:01:30+03:00",
    }
    item["revision_key"] = compute_revision_key(item)
    return item


def envelope_dict(*, kind: str = "daily_brief", items: list[dict] | None = None) -> dict:
    payload = {
        "schema": "tg-companion/envelope",
        "schema_version": 1,
        "envelope_id": "ce1:" + "1" * 64,
        "run": {
            "producer": "codex_automation",
            "producer_id": "automation",
            "kind": kind,
            "run_id": "automation/2026-07-21T05:00:00Z",
            "attempt": 1,
            "scheduled_for": "2026-07-21T08:00:00+03:00",
            "started_at": "2026-07-21T08:00:03+03:00",
            "completed_at": "2026-07-21T08:02:00+03:00",
            "timezone": "Europe/Moscow",
        },
        "window": {
            "from": "2026-07-20T08:00:00+03:00",
            "to": "2026-07-21T08:01:45+03:00",
            "calendar_horizon_to": "2026-08-20T08:01:45+03:00",
        },
        "cursor": {
            "before": "sha256:" + "3" * 64,
            "after": "sha256:" + "4" * 64,
            "complete": True,
        },
        "coverage": [
            {
                "source_id": "gmail:primary",
                "source_type": "gmail",
                "status": "ok",
                "checked_at": "2026-07-21T08:01:00+03:00",
                "cursor_before": "opaque-1",
                "cursor_after": "opaque-2",
                "error_code": None,
            }
        ],
        "items": [_item()] if items is None else items,
        "delivery": {
            "batch_key": "morning:2026-07-21:Europe/Moscow",
            "not_before": "2026-07-21T08:00:00+03:00",
            "expires_at": "2026-07-21T12:00:00+03:00",
        },
    }
    payload["envelope_id"] = compute_envelope_id(payload)
    return payload


@pytest.mark.parametrize(
    ("kind", "section", "expected_kind", "expected_section"),
    [
        ("daily_brief", "mail", EnvelopeKind.DAILY_BRIEF, Section.MAIL),
        ("follow_up_delta", "calendar", EnvelopeKind.FOLLOW_UP_DELTA, Section.CALENDAR),
        ("nightly_attention", "nightly", EnvelopeKind.NIGHTLY_ATTENTION, Section.NIGHTLY),
    ],
)
def test_parse_valid_v1_envelopes(kind, section, expected_kind, expected_section):
    item = _item(section=section, source_id="nightly:optimizer" if section == "nightly" else "gcal:primary")
    payload = envelope_dict(kind=kind, items=[item])

    envelope = parse_envelope(payload)

    assert isinstance(envelope, CompanionEnvelope)
    assert envelope.run.kind is expected_kind
    assert envelope.items[0].section is expected_section
    assert envelope.items[0].facts["status"] == "needs_reply"
    assert isinstance(envelope.coverage, tuple)
    assert envelope.to_dict()["window"]["from"].endswith("Z")


def test_parse_utf8_bytes_and_ignore_bounded_unknown_v1_fields():
    payload = envelope_dict()
    payload["future_extension"] = {"safe": True}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    parsed = parse_envelope_bytes(raw)

    assert parsed.items[0].title == "Нужно ответить сегодня"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value.update(schema_version=2), "unsupported_version"),
        (lambda value: value["run"].update(kind="weekly_digest"), "invalid_enum"),
        (lambda value: value.update(envelope_id="ce1:" + "A" * 64), "invalid_id"),
        (lambda value: value["items"][0].update(item_id="ci1:short"), "invalid_id"),
        (lambda value: value["run"].update(completed_at="2026-07-21T07:59:00+03:00"), "invalid_time_order"),
        (lambda value: value["window"].update(to="2026-07-19T08:00:00+03:00"), "invalid_time_order"),
        (lambda value: value["delivery"].update(expires_at="2026-07-21T07:00:00+03:00"), "invalid_time_order"),
        (lambda value: value["items"][0]["trust"].update(action_policy="execute_allowed"), "invalid_enum"),
        (lambda value: value["items"][0]["trust"].update(content="local_untrusted"), "invalid_trust"),
        (lambda value: value["items"][0].update(summary="<b>external instruction</b>"), "raw_html"),
        (lambda value: value["items"][0].update(summary="unsafe\u0007text"), "control_character"),
        (lambda value: value["items"][0]["facts"].update(api_token="hidden"), "dangerous_fact_key"),
        (lambda value: value["items"][0]["facts"].update(location="https://tracker.invalid/a"), "raw_url"),
        (lambda value: value["items"][0]["facts"].update(nested={"status": "no"}), "invalid_type"),
    ],
)
def test_reject_invalid_contract_cases(mutate, code):
    payload = envelope_dict()
    mutate(payload)

    with pytest.raises(EnvelopeValidationError) as caught:
        parse_envelope(payload)

    assert caught.value.code == code


def test_unavailable_source_cannot_advance_cursor():
    payload = envelope_dict(items=[])
    payload["coverage"][0].update(status="unavailable", error_code="browser_auth", cursor_after="advanced")

    with pytest.raises(EnvelopeValidationError) as caught:
        parse_envelope(payload)

    assert caught.value.code == "cursor_advanced_on_failure"


def test_bytes_parser_rejects_invalid_utf8_duplicate_keys_and_large_payload():
    with pytest.raises(EnvelopeValidationError, match="invalid_utf8"):
        parse_envelope_bytes(b"\xff")
    with pytest.raises(EnvelopeValidationError, match="duplicate_json_key"):
        parse_envelope_bytes(b'{"schema":"one","schema":"two"}')
    with pytest.raises(EnvelopeValidationError, match="payload_too_large"):
        parse_envelope_bytes(b" " * (MAX_ENVELOPE_BYTES + 1))


def test_safe_error_does_not_echo_untrusted_content():
    payload = envelope_dict()
    payload["run"]["kind"] = "DO_NOT_LEAK_THIS_VALUE"

    with pytest.raises(EnvelopeValidationError) as caught:
        parse_envelope(payload)

    assert "DO_NOT_LEAK_THIS_VALUE" not in str(caught.value)
    assert caught.value.path == "$.run.kind"


def test_revision_identity_ignores_prose_observation_provenance_and_change_order():
    first = _item()
    second = deepcopy(first)
    second.update(
        title="Совершенно другая формулировка",
        summary="Другой сгенерированный текст.",
        recommended_action="Иная подсказка.",
        observed_at="2026-07-21T08:01:55+03:00",
        provenance=[{"producer_id": "automation-3", "source_id": "gmail:primary"}],
    )
    second["changes"] = list(reversed(second["changes"]))

    assert compute_revision_key(first) == compute_revision_key(second)


def test_material_structured_change_creates_new_revision_and_delivery_identity():
    first = _item()
    second = deepcopy(first)
    second["urgency_bucket"] = "within_2h"

    assert compute_revision_key(first) != compute_revision_key(second)

    parsed = parse_envelope(envelope_dict()).items[0]
    assert parsed.delivery_key() == compute_delivery_key(parsed)
    assert parsed.delivery_key("telegram") != parsed.delivery_key("local_diagnostics")


def test_canonical_hash_is_stable_for_mapping_and_unicode_normalization():
    first = {"b": 2, "a": "caf\u00e9"}
    second = {"a": "cafe\u0301", "b": 2}

    assert canonical_hash(first) == canonical_hash(second)
