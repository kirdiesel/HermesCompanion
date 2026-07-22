from __future__ import annotations

import html
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .companion_envelope import CompanionEnvelope, CompanionItem


MOSCOW_TIMEZONE = ZoneInfo("Europe/Moscow")
MAX_NONCRITICAL_ITEMS = 5

_SECTION_ORDER = {
    "mail": 0,
    "calendar": 1,
    "follow_up": 2,
    "nightly": 3,
}
_SECTION_TITLES = {
    "mail": "Почта",
    "calendar": "Календарь",
    "follow_up": "Дальнейшие действия",
    "nightly": "Ночной разбор",
}
_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}
_COMPLETENESS_ORDER = {
    "complete": 3,
    "partial": 2,
    "unknown": 1,
}
_IDENTITY_TRUST_ORDER = {
    "managed_connector": 4,
    "authenticated_browser": 3,
    "local_report": 2,
    "unverified": 1,
}
_COVERAGE_DEGRADATION_ORDER = {
    "ok": 0,
    "not_configured": 1,
    "partial": 2,
    "unavailable": 3,
}
_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]\r\n]{1,300})\]\((?:https?://|www\.)[^)\r\n]+\)", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>\r\n]{1,1000}>")
_RAW_URL_RE = re.compile(
    r"(?i)(?<![@\w])(?:https?://|www\.)[^\s<>()]+|"
    r"(?<![@\w])(?:[a-z0-9-]+\.)+[a-z]{2,}/[^\s<>()]*"
)


@dataclass(frozen=True)
class MergedProactiveItem:
    """One exact provider/topic identity after deterministic revision merge."""

    identity_key: str
    item_id: str
    revision_key: str
    section: str
    change: str
    severity: str
    observed_at: datetime
    due_at: datetime | None
    expires_at: datetime
    title: str
    summary: str
    recommended_action: str | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class CoverageWarning:
    source_id: str
    source_label: str
    status: str


@dataclass(frozen=True)
class ProactiveBatch:
    kind: str
    generated_at: datetime
    items: tuple[MergedProactiveItem, ...]
    coverage_warnings: tuple[CoverageWarning, ...] = ()


@dataclass(frozen=True)
class ProactiveDeliveryAction:
    """Framework-neutral outbound action; a later adapter chooses the chat."""

    kind: str
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)
    reply_markup: None = None


def merge_proactive_envelopes(
    envelopes: Iterable[CompanionEnvelope],
    *,
    now: datetime | None = None,
) -> ProactiveBatch:
    """Merge a delivery batch without fuzzy text matching or side effects."""

    materialized = tuple(envelopes)
    reference_time = _reference_time(materialized, now)
    active_envelopes = tuple(
        envelope for envelope in materialized if not _envelope_expired(envelope, reference_time)
    )

    grouped: dict[str, list[CompanionItem]] = defaultdict(list)
    for envelope in active_envelopes:
        for item in envelope.items:
            grouped[_item_identity(item)].append(item)

    merged_items: list[MergedProactiveItem] = []
    health_items: list[CompanionItem] = []
    for identity_key, candidates in grouped.items():
        merged = _merge_identity(identity_key, candidates)
        if merged.expires_at <= reference_time:
            continue
        if merged.change == "resolved":
            continue
        if merged.change in {"source_unavailable", "source_recovered"}:
            health_items.extend(candidates)
            continue
        merged_items.append(merged)

    merged_items.sort(key=_item_sort_key)
    warnings = _coverage_warnings(active_envelopes, health_items)

    return ProactiveBatch(
        kind=_batch_kind(active_envelopes or materialized),
        generated_at=reference_time,
        items=tuple(merged_items),
        coverage_warnings=warnings,
    )


def render_proactive_batch(batch: ProactiveBatch) -> str | None:
    """Render safe plain text, respecting the proactive noise budget."""

    if batch.kind == "follow_up_delta" and not batch.items and not batch.coverage_warnings:
        return None
    if batch.kind == "nightly_attention" and not batch.items and not batch.coverage_warnings:
        return None

    visible_items, omitted_count = _select_visible_items(batch.items)
    local_time = _as_moscow(batch.generated_at)
    lines = [_message_title(batch.kind, local_time)]

    if batch.coverage_warnings:
        lines.append("")
        lines.extend(_render_coverage_warning(warning) for warning in batch.coverage_warnings)

    next_number = 1
    for section in _SECTION_ORDER:
        section_items = tuple(item for item in visible_items if item.section == section)
        if not section_items:
            continue
        lines.extend(["", _SECTION_TITLES[section]])
        if section == "nightly":
            all_nightly = tuple(item for item in batch.items if item.section == "nightly")
            critical_count = sum(item.severity == "critical" for item in all_nightly)
            urgency = f", из них срочных — {critical_count}" if critical_count else ""
            lines.append(
                f"{next_number}. Вопросов для разбора — {len(all_nightly)}{urgency}. "
                "Напишите «покажи ночной разбор» — покажу их по одному."
            )
            next_number += 1
            continue
        for item in section_items:
            lines.append(_render_item(item, next_number))
            next_number += 1

    if not visible_items and not batch.coverage_warnings and batch.kind == "daily_brief":
        lines.extend(["", "Срочного и требующего решения нет."])

    if omitted_count:
        lines.extend(
            [
                "",
                f"Ещё {omitted_count} менее срочных пунктов — покажу по запросу.",
            ]
        )

    return "\n".join(lines)


def plan_proactive_delivery(
    envelopes: Iterable[CompanionEnvelope],
    *,
    now: datetime | None = None,
) -> ProactiveDeliveryAction | None:
    """Return a neutral, informational send action or a delta no-op."""

    batch = merge_proactive_envelopes(envelopes, now=now)
    text = render_proactive_batch(batch)
    if text is None:
        return None
    return ProactiveDeliveryAction(
        kind="send_message",
        text=text,
        metadata={
            "proactive_kind": batch.kind,
            "task_final": False,
            "suppress_completion_feedback": True,
        },
        reply_markup=None,
    )


def _merge_identity(identity_key: str, candidates: Sequence[CompanionItem]) -> MergedProactiveItem:
    selected = max(candidates, key=_content_precedence_key)
    complete_deadlines = tuple(
        item.due_at
        for item in candidates
        if item.due_at is not None and _trust_value(item, "completeness") == "complete"
    )
    deadlines = complete_deadlines or tuple(item.due_at for item in candidates if item.due_at is not None)
    due_at = min(deadlines) if deadlines else None
    severity = min(
        (_enum_value(item.severity) for item in candidates),
        key=lambda value: (_SEVERITY_ORDER.get(value, 99), value),
    )
    recommendation = selected.recommended_action or next(
        (
            item.recommended_action
            for item in sorted(candidates, key=_content_precedence_key, reverse=True)
            if item.recommended_action
        ),
        None,
    )
    return MergedProactiveItem(
        identity_key=identity_key,
        item_id=selected.item_id,
        revision_key=selected.revision_key,
        section=_enum_value(selected.section),
        change=_enum_value(selected.change),
        severity=severity,
        observed_at=selected.observed_at,
        due_at=due_at,
        expires_at=selected.expires_at,
        title=selected.title,
        summary=selected.summary,
        recommended_action=recommendation,
        source_ids=tuple(sorted({item.source_id for item in candidates})),
    )


def _content_precedence_key(item: CompanionItem) -> tuple[object, ...]:
    return (
        _COMPLETENESS_ORDER.get(_trust_value(item, "completeness"), 0),
        _IDENTITY_TRUST_ORDER.get(_trust_value(item, "identity"), 0),
        _datetime_key(item.observed_at),
        item.revision_key,
        item.item_id,
    )


def _item_sort_key(item: MergedProactiveItem) -> tuple[object, ...]:
    deadline = _datetime_key(item.due_at) if item.due_at is not None else float("inf")
    return (
        _SECTION_ORDER.get(item.section, 99),
        _SEVERITY_ORDER.get(item.severity, 99),
        deadline,
        item.identity_key,
        item.revision_key,
    )


def _select_visible_items(
    items: Sequence[MergedProactiveItem],
) -> tuple[tuple[MergedProactiveItem, ...], int]:
    regular_items = tuple(item for item in items if item.section != "nightly")
    nightly_items = tuple(item for item in items if item.section == "nightly")
    critical_ids = {item.identity_key for item in regular_items if item.severity == "critical"}

    # Nightly details are one on-demand summary in the morning, so they consume
    # at most one noncritical slot instead of crowding out mail/calendar facts.
    critical_nightly = any(item.severity == "critical" for item in nightly_items)
    nightly_representative = min(nightly_items, key=_selection_priority_key) if nightly_items else None
    candidates = [item for item in regular_items if item.severity != "critical"]
    if nightly_representative is not None and not critical_nightly:
        candidates.append(nightly_representative)
    selected_other_ids = {
        item.identity_key
        for item in sorted(candidates, key=_selection_priority_key)[:MAX_NONCRITICAL_ITEMS]
    }
    nightly_selected = critical_nightly or (
        nightly_representative is not None
        and nightly_representative.identity_key in selected_other_ids
    )
    selected = tuple(
        item
        for item in items
        if item.identity_key in critical_ids
        or item.identity_key in selected_other_ids
        or (nightly_selected and item.section == "nightly")
    )
    omitted_regular = sum(item not in selected for item in regular_items)
    omitted_nightly_group = int(bool(nightly_items) and not nightly_selected)
    return selected, omitted_regular + omitted_nightly_group


def _selection_priority_key(item: MergedProactiveItem) -> tuple[object, ...]:
    deadline = _datetime_key(item.due_at) if item.due_at is not None else float("inf")
    return (
        _SEVERITY_ORDER.get(item.severity, 99),
        deadline,
        _SECTION_ORDER.get(item.section, 99),
        item.identity_key,
        item.revision_key,
    )


def _coverage_warnings(
    envelopes: Sequence[CompanionEnvelope],
    health_items: Sequence[CompanionItem],
) -> tuple[CoverageWarning, ...]:
    latest_by_source: dict[str, object] = {}
    for envelope in envelopes:
        for coverage in envelope.coverage:
            existing = latest_by_source.get(coverage.source_id)
            if existing is None or _coverage_precedence_key(coverage) > _coverage_precedence_key(existing):
                latest_by_source[coverage.source_id] = coverage

    warnings: dict[str, CoverageWarning] = {}
    for source_id, coverage in latest_by_source.items():
        status = _enum_value(coverage.status)
        if status == "ok":
            continue
        warnings[source_id] = CoverageWarning(
            source_id=source_id,
            source_label=_source_label(coverage),
            status=status,
        )

    for item in health_items:
        if _enum_value(item.change) != "source_unavailable" or item.source_id in warnings:
            continue
        warnings[item.source_id] = CoverageWarning(
            source_id=item.source_id,
            source_label=_source_label(item),
            status="unavailable",
        )

    return tuple(
        sorted(
            warnings.values(),
            key=lambda warning: (warning.source_label.casefold(), warning.source_id),
        )
    )


def _coverage_precedence_key(coverage: object) -> tuple[object, ...]:
    checked_at = getattr(coverage, "checked_at")
    status = _enum_value(getattr(coverage, "status"))
    return (
        _datetime_key(checked_at),
        _COVERAGE_DEGRADATION_ORDER.get(status, 99),
        status,
    )


def _render_coverage_warning(warning: CoverageWarning) -> str:
    label = _safe_plain_text(warning.source_label, limit=80)
    if warning.status == "partial":
        return f"Источник «{label}» проверен не полностью; часть данных могла не попасть в сводку."
    if warning.status == "not_configured":
        return f"Источник «{label}» не настроен и не учитывался в сводке."
    return f"Проверка источника «{label}» не завершилась; это не означает, что новых данных нет."


def _render_item(item: MergedProactiveItem, number: int) -> str:
    title = _safe_plain_text(item.title, limit=240)
    summary = _safe_plain_text(item.summary, limit=520)
    recommendation = _safe_plain_text(item.recommended_action or "", limit=260)
    prefix_parts: list[str] = []
    if item.severity == "critical":
        prefix_parts.append("🔴")
    if item.due_at is not None:
        prefix_parts.append(_format_deadline(item.due_at))
    prefix = " ".join(prefix_parts)
    if prefix:
        prefix = f"{prefix} — "

    first_line = f"{number}. {prefix}{title}"
    detail_parts = [part for part in (summary, recommendation) if part]
    if not detail_parts:
        return first_line
    return f"{first_line}. {'; '.join(dict.fromkeys(detail_parts))}."


def _safe_plain_text(value: str, *, limit: int) -> str:
    text = html.unescape(str(value))
    text = _MARKDOWN_LINK_RE.sub(lambda match: match.group(1), text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _RAW_URL_RE.sub("[ссылка скрыта]", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("C") or character in "\t\n"
    )
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _message_title(kind: str, local_time: datetime) -> str:
    if kind == "follow_up_delta":
        return f"Изменения · {local_time:%H:%M}, МСК"
    if kind == "nightly_attention":
        return f"Ночной разбор · {local_time.day} {_MONTHS[local_time.month - 1]}, МСК"
    return f"Утренняя сводка · {local_time.day} {_MONTHS[local_time.month - 1]}, МСК"


def _format_deadline(value: datetime) -> str:
    local = _as_moscow(value)
    return f"до {local:%d.%m, %H:%M}"


def _source_label(value: object) -> str:
    source_id = str(getattr(value, "source_id", "")).casefold()
    source_type = _enum_value(getattr(value, "source_type", "")).casefold()
    combined = f"{source_type} {source_id}"
    if "yandex" in combined:
        return "Яндекс Почта"
    if "gmail" in combined:
        return "Gmail"
    if any(marker in combined for marker in ("google_calendar", "gcal", "calendar")):
        return "Google Календарь"
    if "nightly" in combined:
        return "ночной разбор"
    return "неизвестный источник"


def _batch_kind(envelopes: Sequence[CompanionEnvelope]) -> str:
    if any(str(envelope.delivery.batch_key).startswith("morning:") for envelope in envelopes):
        return "daily_brief"
    kinds = {_enum_value(envelope.run.kind) for envelope in envelopes}
    if "daily_brief" in kinds:
        return "daily_brief"
    if kinds == {"nightly_attention"}:
        return "nightly_attention"
    return "follow_up_delta"


def _reference_time(
    envelopes: Sequence[CompanionEnvelope],
    now: datetime | None,
) -> datetime:
    if now is not None:
        _require_aware(now)
        return now
    completed = tuple(envelope.run.completed_at for envelope in envelopes)
    if completed:
        return max(completed, key=_datetime_key)
    return datetime.now(timezone.utc)


def _envelope_expired(envelope: CompanionEnvelope, now: datetime) -> bool:
    return envelope.delivery.expires_at <= now


def _item_identity(item: CompanionItem) -> str:
    topic_key = item.topic_key.strip() if item.topic_key else ""
    entity_key = item.entity_key.strip() if item.entity_key else ""
    return topic_key or entity_key or item.item_id


def _trust_value(item: CompanionItem, field_name: str) -> str:
    return _enum_value(getattr(item.trust, field_name))


def _enum_value(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _datetime_key(value: datetime) -> float:
    _require_aware(value)
    return value.timestamp()


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("proactive runtime requires timezone-aware datetimes")


def _as_moscow(value: datetime) -> datetime:
    _require_aware(value)
    return value.astimezone(MOSCOW_TIMEZONE)
