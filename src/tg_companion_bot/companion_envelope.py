"""Strict, dependency-free contract for proactive Companion envelopes.

The module deliberately does not know anything about Telegram, Hermes, files, or
network transports.  It turns an untrusted JSON object into small immutable
domain objects and exposes deterministic identity helpers for producers and the
local delivery pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, StrEnum
import hashlib
import json
import math
import re
import unicodedata
from typing import Any, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA = "tg-companion/envelope"
SCHEMA_VERSION = 1
MAX_ENVELOPE_BYTES = 256 * 1024
MAX_ITEMS = 200
MAX_COVERAGE = 32
MAX_FACTS = 48
MAX_CHANGES = 32
MAX_PROVENANCE = 16
MAX_JSON_DEPTH = 12
MAX_JSON_NODES = 12_000
MAX_DELIVERY_TTL = timedelta(days=30)


class EnvelopeKind(StrEnum):
    DAILY_BRIEF = "daily_brief"
    FOLLOW_UP_DELTA = "follow_up_delta"
    NIGHTLY_ATTENTION = "nightly_attention"


class CoverageStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


class Section(StrEnum):
    MAIL = "mail"
    CALENDAR = "calendar"
    FOLLOW_UP = "follow_up"
    NIGHTLY = "nightly"


class ChangeKind(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    APPROACHING = "approaching"
    RESOLVED = "resolved"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_RECOVERED = "source_recovered"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class UrgencyBucket(StrEnum):
    OVERDUE = "overdue"
    WITHIN_2H = "within_2h"
    WITHIN_6H = "within_6h"
    WITHIN_24H = "within_24h"
    WITHIN_48H = "within_48h"
    WITHIN_7D = "within_7d"
    LATER = "later"
    NONE = "none"


class ContentTrust(StrEnum):
    EXTERNAL_UNTRUSTED = "external_untrusted"
    LOCAL_UNTRUSTED = "local_untrusted"


class IdentityTrust(StrEnum):
    MANAGED_CONNECTOR = "managed_connector"
    AUTHENTICATED_BROWSER = "authenticated_browser"
    LOCAL_REPORT = "local_report"
    UNVERIFIED = "unverified"


class Completeness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ActionPolicy(StrEnum):
    PROPOSAL_ONLY = "proposal_only"


class EnvelopeValidationError(ValueError):
    """A validation failure whose text never contains the rejected payload."""

    def __init__(self, code: str, path: str = "$", message: str = "invalid envelope"):
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


FactScalar: TypeAlias = str | int | float | bool | None
FactValue: TypeAlias = FactScalar | tuple[FactScalar, ...]


@dataclass(frozen=True)
class FrozenMapping(Mapping[str, FactValue]):
    """A small deterministic, immutable mapping used for item facts."""

    _items: tuple[tuple[str, FactValue], ...] = ()

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, key: str) -> FactValue:
        for current, value in self._items:
            if current == key:
                return value
        raise KeyError(key)

    def items(self) -> tuple[tuple[str, FactValue], ...]:  # type: ignore[override]
        return self._items


@dataclass(frozen=True)
class EnvelopeRun:
    producer: str
    producer_id: str
    kind: EnvelopeKind
    run_id: str
    attempt: int
    scheduled_for: datetime
    started_at: datetime
    completed_at: datetime
    timezone: str


@dataclass(frozen=True)
class EnvelopeWindow:
    from_at: datetime
    to: datetime
    calendar_horizon_to: datetime | None

    @property
    def from_(self) -> datetime:
        """Readable alias for the JSON field named ``from``."""

        return self.from_at


@dataclass(frozen=True)
class EnvelopeCursor:
    before: str | None
    after: str | None
    complete: bool


@dataclass(frozen=True)
class SourceCoverage:
    source_id: str
    source_type: str
    status: CoverageStatus
    checked_at: datetime
    cursor_before: str | None
    cursor_after: str | None
    error_code: str | None


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: FactValue
    after: FactValue


@dataclass(frozen=True)
class Provenance:
    producer_id: str
    source_id: str


@dataclass(frozen=True)
class ItemTrust:
    content: ContentTrust
    identity: IdentityTrust
    completeness: Completeness
    action_policy: ActionPolicy
    prompt_injection_suspected: bool


@dataclass(frozen=True)
class CompanionItem:
    item_id: str
    entity_key: str | None
    topic_key: str | None
    revision_key: str
    section: Section
    source_id: str
    change: ChangeKind
    severity: Severity
    urgency_bucket: UrgencyBucket
    observed_at: datetime
    occurred_at: datetime | None
    due_at: datetime | None
    title: str
    summary: str
    recommended_action: str
    facts: FrozenMapping
    changes: tuple[FieldChange, ...]
    provenance: tuple[Provenance, ...]
    trust: ItemTrust
    expires_at: datetime

    @property
    def identity_key(self) -> str:
        return self.topic_key or self.entity_key or ""

    def computed_revision_key(self) -> str:
        return compute_revision_key(self)

    def delivery_key(self, delivery_surface: str = "telegram") -> str:
        return compute_delivery_key(self, delivery_surface)


@dataclass(frozen=True)
class EnvelopeDelivery:
    batch_key: str
    not_before: datetime
    expires_at: datetime


@dataclass(frozen=True)
class CompanionEnvelope:
    schema: str
    schema_version: int
    envelope_id: str
    run: EnvelopeRun
    window: EnvelopeWindow
    cursor: EnvelopeCursor
    coverage: tuple[SourceCoverage, ...]
    items: tuple[CompanionItem, ...]
    delivery: EnvelopeDelivery

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)

    def canonical_json(self) -> str:
        return canonical_json(self)

    def canonical_hash(self) -> str:
        return canonical_hash(self)

    def canonical_payload_hash(self) -> str:
        return canonical_payload_hash(self)

    def computed_envelope_id(self) -> str:
        return compute_envelope_id(self)


# Compatibility aliases make the contract vocabulary easy to discover without
# forcing consumers to depend on a single naming preference.
RunInfo = EnvelopeRun
TimeWindow = EnvelopeWindow
CursorInfo = EnvelopeCursor
Coverage = SourceCoverage
Delivery = EnvelopeDelivery
Trust = ItemTrust
ItemChange = FieldChange
EnvelopeError = EnvelopeValidationError


_ENVELOPE_ID = re.compile(r"ce1:[0-9a-f]{64}\Z")
_ITEM_ID = re.compile(r"ci1:[0-9a-f]{64}\Z")
_SHA256_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+%=~-]*\Z")
_SAFE_FACT_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_TIMEZONE_NAME = re.compile(r"[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*\Z")
_RAW_HTML = re.compile(r"<(?:!doctype\b|!--|/?[A-Za-z][^>]*)>", re.IGNORECASE | re.DOTALL)
_URL = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_DANGEROUS_KEY_PARTS = {
    "auth",
    "authorization",
    "chat",
    "command",
    "cookie",
    "credential",
    "credentials",
    "file",
    "header",
    "key",
    "oauth",
    "password",
    "path",
    "prompt",
    "secret",
    "session",
    "token",
    "tool",
}


def _fail(code: str, path: str, message: str) -> None:
    raise EnvelopeValidationError(code, path, message)


def _required(obj: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in obj:
        _fail("missing_field", f"{path}.{key}", "required field is missing")
    return obj[key]


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail("invalid_type", path, "expected object")
    return value


def _array(value: Any, path: str, *, maximum: int, minimum: int = 0) -> Sequence[Any]:
    if not isinstance(value, list):
        _fail("invalid_type", path, "expected array")
    if not minimum <= len(value) <= maximum:
        _fail("invalid_size", path, "array length is outside the permitted range")
    return value


def _has_control(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)


def _text(
    value: Any,
    path: str,
    *,
    minimum: int = 0,
    maximum: int,
    plain: bool = True,
    trim: bool = True,
) -> str:
    if not isinstance(value, str):
        _fail("invalid_type", path, "expected string")
    if not minimum <= len(value) <= maximum:
        _fail("invalid_size", path, "string length is outside the permitted range")
    if trim and value != value.strip():
        _fail("invalid_content", path, "leading or trailing whitespace is not permitted")
    if _has_control(value):
        _fail("control_character", path, "control characters are not permitted")
    if plain and _RAW_HTML.search(value):
        _fail("raw_html", path, "raw HTML is not permitted")
    return value


def _identifier(value: Any, path: str, *, maximum: int = 512) -> str:
    result = _text(value, path, minimum=1, maximum=maximum)
    if not _SAFE_IDENTIFIER.fullmatch(result):
        _fail("invalid_id", path, "identifier has an invalid format")
    return result


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("invalid_type", path, "expected boolean")
    return value


def _integer(value: Any, path: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("invalid_type", path, "expected integer")
    if not minimum <= value <= maximum:
        _fail("invalid_value", path, "integer is outside the permitted range")
    return value


def _enum(enum_type: type[StrEnum], value: Any, path: str) -> StrEnum:
    if not isinstance(value, str):
        _fail("invalid_type", path, "expected enum string")
    try:
        return enum_type(value)
    except ValueError:
        _fail("invalid_enum", path, "value is not permitted")


def _timestamp(value: Any, path: str) -> datetime:
    raw = _text(value, path, minimum=20, maximum=40, plain=False)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        _fail("invalid_timestamp", path, "expected an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("naive_timestamp", path, "timestamp must include an offset")
    if parsed.utcoffset() is not None and abs(parsed.utcoffset()) > timedelta(hours=14):
        _fail("invalid_timestamp", path, "timestamp offset is outside the permitted range")
    return parsed


def _optional_timestamp(value: Any, path: str) -> datetime | None:
    return None if value is None else _timestamp(value, path)


def _optional_string(value: Any, path: str, *, maximum: int) -> str | None:
    return None if value is None else _text(value, path, minimum=1, maximum=maximum)


def _hash_id(value: Any, path: str, *, item: bool = False, envelope: bool = False) -> str:
    result = _text(value, path, minimum=1, maximum=128)
    pattern = _ENVELOPE_ID if envelope else _ITEM_ID if item else _SHA256_ID
    if not pattern.fullmatch(result):
        _fail("invalid_id", path, "hash identifier has an invalid format")
    return result


def _dangerous_fact_key(key: str) -> bool:
    parts = tuple(part for part in key.casefold().split("_") if part)
    return any(part in _DANGEROUS_KEY_PARTS for part in parts)


def _fact_scalar(value: Any, path: str) -> FactScalar:
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, str):
            result = _text(value, path, maximum=512)
            if _URL.search(result):
                _fail("raw_url", path, "full URLs are not permitted in structured facts")
            return result
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**63 - 1:
            _fail("invalid_value", path, "integer is outside the permitted range")
        if isinstance(value, float) and not math.isfinite(value):
            _fail("invalid_value", path, "non-finite numbers are not permitted")
        return value
    _fail("invalid_type", path, "expected a scalar JSON value")


def _fact_value(value: Any, path: str) -> FactValue:
    if isinstance(value, list):
        values = _array(value, path, maximum=32)
        return tuple(_fact_scalar(entry, f"{path}[{index}]") for index, entry in enumerate(values))
    return _fact_scalar(value, path)


def _facts(value: Any, path: str) -> FrozenMapping:
    obj = _object(value, path)
    if len(obj) > MAX_FACTS:
        _fail("invalid_size", path, "too many structured facts")
    parsed: list[tuple[str, FactValue]] = []
    for key in sorted(obj):
        if not isinstance(key, str) or not _SAFE_FACT_KEY.fullmatch(key):
            _fail("invalid_fact_key", path, "fact keys must be lower snake-case identifiers")
        if _dangerous_fact_key(key):
            _fail("dangerous_fact_key", f"{path}.{key}", "sensitive or executable fields are not permitted")
        parsed.append((key, _fact_value(obj[key], f"{path}.{key}")))
    return FrozenMapping(tuple(parsed))


def _parse_run(value: Any, path: str) -> EnvelopeRun:
    obj = _object(value, path)
    timezone_name = _text(_required(obj, "timezone", path), f"{path}.timezone", minimum=1, maximum=64)
    if not _TIMEZONE_NAME.fullmatch(timezone_name):
        _fail("invalid_timezone", f"{path}.timezone", "timezone name has an invalid format")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        _fail("invalid_timezone", f"{path}.timezone", "timezone is not available")
    scheduled_for = _timestamp(_required(obj, "scheduled_for", path), f"{path}.scheduled_for")
    started_at = _timestamp(_required(obj, "started_at", path), f"{path}.started_at")
    completed_at = _timestamp(_required(obj, "completed_at", path), f"{path}.completed_at")
    if completed_at < started_at:
        _fail("invalid_time_order", f"{path}.completed_at", "completion precedes start")
    if completed_at < scheduled_for:
        _fail("invalid_time_order", f"{path}.completed_at", "completion precedes scheduled time")
    return EnvelopeRun(
        producer=_identifier(_required(obj, "producer", path), f"{path}.producer", maximum=64),
        producer_id=_identifier(_required(obj, "producer_id", path), f"{path}.producer_id", maximum=128),
        kind=_enum(EnvelopeKind, _required(obj, "kind", path), f"{path}.kind"),  # type: ignore[arg-type]
        run_id=_identifier(_required(obj, "run_id", path), f"{path}.run_id", maximum=256),
        attempt=_integer(_required(obj, "attempt", path), f"{path}.attempt", minimum=1, maximum=1000),
        scheduled_for=scheduled_for,
        started_at=started_at,
        completed_at=completed_at,
        timezone=timezone_name,
    )


def _parse_window(value: Any, path: str) -> EnvelopeWindow:
    obj = _object(value, path)
    from_at = _timestamp(_required(obj, "from", path), f"{path}.from")
    to = _timestamp(_required(obj, "to", path), f"{path}.to")
    horizon = _optional_timestamp(obj.get("calendar_horizon_to"), f"{path}.calendar_horizon_to")
    if to < from_at:
        _fail("invalid_time_order", f"{path}.to", "window end precedes window start")
    if horizon is not None and horizon < to:
        _fail("invalid_time_order", f"{path}.calendar_horizon_to", "calendar horizon precedes window end")
    return EnvelopeWindow(from_at=from_at, to=to, calendar_horizon_to=horizon)


def _parse_cursor(value: Any, path: str) -> EnvelopeCursor:
    obj = _object(value, path)
    before_raw = _required(obj, "before", path)
    after_raw = _required(obj, "after", path)
    before = None if before_raw is None else _hash_id(before_raw, f"{path}.before")
    after = None if after_raw is None else _hash_id(after_raw, f"{path}.after")
    return EnvelopeCursor(before=before, after=after, complete=_boolean(_required(obj, "complete", path), f"{path}.complete"))


def _parse_coverage(value: Any, path: str, index: int) -> SourceCoverage:
    obj = _object(value, path)
    status = _enum(CoverageStatus, _required(obj, "status", path), f"{path}.status")
    error_raw = _required(obj, "error_code", path)
    error_code = _optional_string(error_raw, f"{path}.error_code", maximum=64)
    if error_code is not None and not _SAFE_ERROR_CODE.fullmatch(error_code):
        _fail("invalid_error_code", f"{path}.error_code", "error code has an invalid format")
    if status == CoverageStatus.OK and error_code is not None:
        _fail("invalid_coverage", f"{path}.error_code", "successful coverage cannot carry an error")
    if status in {CoverageStatus.PARTIAL, CoverageStatus.UNAVAILABLE} and error_code is None:
        _fail("invalid_coverage", f"{path}.error_code", "degraded coverage requires an error code")
    cursor_before = _optional_string(_required(obj, "cursor_before", path), f"{path}.cursor_before", maximum=512)
    cursor_after = _optional_string(_required(obj, "cursor_after", path), f"{path}.cursor_after", maximum=512)
    if status == CoverageStatus.UNAVAILABLE and cursor_after not in {None, cursor_before}:
        _fail("cursor_advanced_on_failure", f"{path}.cursor_after", "an unavailable source cannot advance its cursor")
    return SourceCoverage(
        source_id=_identifier(_required(obj, "source_id", path), f"{path}.source_id", maximum=128),
        source_type=_identifier(_required(obj, "source_type", path), f"{path}.source_type", maximum=64),
        status=status,  # type: ignore[arg-type]
        checked_at=_timestamp(_required(obj, "checked_at", path), f"{path}.checked_at"),
        cursor_before=cursor_before,
        cursor_after=cursor_after,
        error_code=error_code,
    )


def _parse_change(value: Any, path: str) -> FieldChange:
    obj = _object(value, path)
    field = _text(_required(obj, "field", path), f"{path}.field", minimum=1, maximum=64)
    if not _SAFE_FACT_KEY.fullmatch(field):
        _fail("invalid_fact_key", f"{path}.field", "changed field must be a lower snake-case identifier")
    if _dangerous_fact_key(field):
        _fail("dangerous_fact_key", f"{path}.field", "sensitive or executable fields are not permitted")
    return FieldChange(
        field=field,
        before=_fact_value(_required(obj, "before", path), f"{path}.before"),
        after=_fact_value(_required(obj, "after", path), f"{path}.after"),
    )


def _parse_provenance(value: Any, path: str) -> Provenance:
    obj = _object(value, path)
    return Provenance(
        producer_id=_identifier(_required(obj, "producer_id", path), f"{path}.producer_id", maximum=128),
        source_id=_identifier(_required(obj, "source_id", path), f"{path}.source_id", maximum=128),
    )


def _parse_trust(value: Any, path: str, section: Section) -> ItemTrust:
    obj = _object(value, path)
    content = _enum(ContentTrust, _required(obj, "content", path), f"{path}.content")
    if section in {Section.MAIL, Section.CALENDAR} and content != ContentTrust.EXTERNAL_UNTRUSTED:
        _fail("invalid_trust", f"{path}.content", "mail and calendar content must be external_untrusted")
    if section == Section.NIGHTLY and content != ContentTrust.LOCAL_UNTRUSTED:
        _fail("invalid_trust", f"{path}.content", "nightly content must be local_untrusted")
    action_policy = _enum(ActionPolicy, _required(obj, "action_policy", path), f"{path}.action_policy")
    return ItemTrust(
        content=content,  # type: ignore[arg-type]
        identity=_enum(IdentityTrust, _required(obj, "identity", path), f"{path}.identity"),  # type: ignore[arg-type]
        completeness=_enum(Completeness, _required(obj, "completeness", path), f"{path}.completeness"),  # type: ignore[arg-type]
        action_policy=action_policy,  # type: ignore[arg-type]
        prompt_injection_suspected=_boolean(
            _required(obj, "prompt_injection_suspected", path), f"{path}.prompt_injection_suspected"
        ),
    )


def _parse_item(value: Any, path: str) -> CompanionItem:
    obj = _object(value, path)
    entity_key = _optional_string(_required(obj, "entity_key", path), f"{path}.entity_key", maximum=512)
    topic_key = _optional_string(_required(obj, "topic_key", path), f"{path}.topic_key", maximum=512)
    if entity_key is None and topic_key is None:
        _fail("missing_identity", path, "an entity_key or topic_key is required")
    if entity_key is not None and not _SAFE_IDENTIFIER.fullmatch(entity_key):
        _fail("invalid_id", f"{path}.entity_key", "entity key has an invalid format")
    if topic_key is not None and not _SAFE_IDENTIFIER.fullmatch(topic_key):
        _fail("invalid_id", f"{path}.topic_key", "topic key has an invalid format")
    section = _enum(Section, _required(obj, "section", path), f"{path}.section")
    observed_at = _timestamp(_required(obj, "observed_at", path), f"{path}.observed_at")
    expires_at = _timestamp(_required(obj, "expires_at", path), f"{path}.expires_at")
    if expires_at <= observed_at:
        _fail("invalid_time_order", f"{path}.expires_at", "item expiry must follow observation")
    if expires_at - observed_at > MAX_DELIVERY_TTL:
        _fail("invalid_ttl", f"{path}.expires_at", "item TTL exceeds 30 days")
    changes_raw = _array(_required(obj, "changes", path), f"{path}.changes", maximum=MAX_CHANGES)
    provenance_raw = _array(
        _required(obj, "provenance", path), f"{path}.provenance", maximum=MAX_PROVENANCE, minimum=1
    )
    return CompanionItem(
        item_id=_hash_id(_required(obj, "item_id", path), f"{path}.item_id", item=True),
        entity_key=entity_key,
        topic_key=topic_key,
        revision_key=_hash_id(_required(obj, "revision_key", path), f"{path}.revision_key"),
        section=section,  # type: ignore[arg-type]
        source_id=_identifier(_required(obj, "source_id", path), f"{path}.source_id", maximum=128),
        change=_enum(ChangeKind, _required(obj, "change", path), f"{path}.change"),  # type: ignore[arg-type]
        severity=_enum(Severity, _required(obj, "severity", path), f"{path}.severity"),  # type: ignore[arg-type]
        urgency_bucket=_enum(
            UrgencyBucket, _required(obj, "urgency_bucket", path), f"{path}.urgency_bucket"
        ),  # type: ignore[arg-type]
        observed_at=observed_at,
        occurred_at=_optional_timestamp(_required(obj, "occurred_at", path), f"{path}.occurred_at"),
        due_at=_optional_timestamp(_required(obj, "due_at", path), f"{path}.due_at"),
        title=_text(_required(obj, "title", path), f"{path}.title", minimum=1, maximum=200),
        summary=_text(_required(obj, "summary", path), f"{path}.summary", minimum=1, maximum=1000),
        recommended_action=_text(
            _required(obj, "recommended_action", path), f"{path}.recommended_action", maximum=300
        ),
        facts=_facts(_required(obj, "facts", path), f"{path}.facts"),
        changes=tuple(_parse_change(entry, f"{path}.changes[{index}]") for index, entry in enumerate(changes_raw)),
        provenance=tuple(
            _parse_provenance(entry, f"{path}.provenance[{index}]")
            for index, entry in enumerate(provenance_raw)
        ),
        trust=_parse_trust(_required(obj, "trust", path), f"{path}.trust", section),  # type: ignore[arg-type]
        expires_at=expires_at,
    )


def _parse_delivery(value: Any, path: str) -> EnvelopeDelivery:
    obj = _object(value, path)
    not_before = _timestamp(_required(obj, "not_before", path), f"{path}.not_before")
    expires_at = _timestamp(_required(obj, "expires_at", path), f"{path}.expires_at")
    if expires_at <= not_before:
        _fail("invalid_time_order", f"{path}.expires_at", "delivery expiry must follow not_before")
    if expires_at - not_before > MAX_DELIVERY_TTL:
        _fail("invalid_ttl", f"{path}.expires_at", "delivery TTL exceeds 30 days")
    return EnvelopeDelivery(
        batch_key=_identifier(_required(obj, "batch_key", path), f"{path}.batch_key", maximum=160),
        not_before=not_before,
        expires_at=expires_at,
    )


def _validate_json_shape(value: Any, path: str = "$", depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES:
        _fail("payload_too_complex", path, "JSON node limit exceeded")
    if depth > MAX_JSON_DEPTH:
        _fail("payload_too_deep", path, "JSON nesting limit exceeded")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            _fail("invalid_json_number", path, "non-finite numbers are not permitted")
        if isinstance(value, str) and len(value) > 8192:
            _fail("invalid_size", path, "JSON string is too long")
        return
    if isinstance(value, list):
        if len(value) > MAX_JSON_NODES:
            _fail("payload_too_complex", path, "JSON array is too large")
        for index, entry in enumerate(value):
            _validate_json_shape(entry, f"{path}[{index}]", depth + 1, counter)
        return
    if isinstance(value, dict):
        if len(value) > MAX_JSON_NODES:
            _fail("payload_too_complex", path, "JSON object is too large")
        for key, entry in value.items():
            if not isinstance(key, str):
                _fail("invalid_json_key", path, "object keys must be strings")
            _validate_json_shape(entry, f"{path}.{key}", depth + 1, counter)
        return
    _fail("invalid_json_type", path, "value is not JSON-compatible")


def parse_envelope(value: Mapping[str, Any]) -> CompanionEnvelope:
    """Parse and validate a JSON-shaped mapping into a frozen envelope.

    Unknown fields are ignored for schema major version 1, but the entire input
    remains bounded and must be JSON-compatible.
    """

    if not isinstance(value, dict):
        _fail("invalid_type", "$", "expected object")
    _validate_json_shape(value)
    try:
        approximate_size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        _fail("invalid_json", "$", "input is not valid JSON data")
    if approximate_size > MAX_ENVELOPE_BYTES:
        _fail("payload_too_large", "$", "envelope exceeds the byte limit")
    schema = _text(_required(value, "schema", "$"), "$.schema", minimum=1, maximum=64)
    if schema != SCHEMA:
        _fail("invalid_schema", "$.schema", "unsupported schema")
    version = _integer(_required(value, "schema_version", "$"), "$.schema_version", minimum=1, maximum=2**31 - 1)
    if version != SCHEMA_VERSION:
        _fail("unsupported_version", "$.schema_version", "unsupported schema version")
    run = _parse_run(_required(value, "run", "$"), "$.run")
    window = _parse_window(_required(value, "window", "$"), "$.window")
    if window.to > run.completed_at + timedelta(minutes=5):
        _fail("invalid_time_order", "$.window.to", "window end is after run completion")
    coverage_raw = _array(_required(value, "coverage", "$"), "$.coverage", maximum=MAX_COVERAGE, minimum=1)
    coverage = tuple(_parse_coverage(entry, f"$.coverage[{index}]", index) for index, entry in enumerate(coverage_raw))
    source_ids = [entry.source_id for entry in coverage]
    if len(source_ids) != len(set(source_ids)):
        _fail("duplicate_source", "$.coverage", "coverage source_id values must be unique")
    for index, entry in enumerate(coverage):
        if entry.checked_at > run.completed_at + timedelta(minutes=5):
            _fail("invalid_time_order", f"$.coverage[{index}].checked_at", "coverage check is after run completion")
    items_raw = _array(_required(value, "items", "$"), "$.items", maximum=MAX_ITEMS)
    items = tuple(_parse_item(entry, f"$.items[{index}]") for index, entry in enumerate(items_raw))
    item_ids = [entry.item_id for entry in items]
    if len(item_ids) != len(set(item_ids)):
        _fail("duplicate_item", "$.items", "item_id values must be unique")
    for index, entry in enumerate(items):
        if entry.observed_at > run.completed_at + timedelta(minutes=5):
            _fail("invalid_time_order", f"$.items[{index}].observed_at", "observation is after run completion")
    delivery = _parse_delivery(_required(value, "delivery", "$"), "$.delivery")
    return CompanionEnvelope(
        schema=schema,
        schema_version=version,
        envelope_id=_hash_id(_required(value, "envelope_id", "$"), "$.envelope_id", envelope=True),
        run=run,
        window=window,
        cursor=_parse_cursor(_required(value, "cursor", "$"), "$.cursor"),
        coverage=coverage,
        items=items,
        delivery=delivery,
    )


class _DuplicateJsonKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError


def parse_envelope_bytes(payload: bytes | bytearray | memoryview) -> CompanionEnvelope:
    """Parse one UTF-8 JSON envelope while returning only safe error details."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        _fail("invalid_type", "$", "expected UTF-8 bytes")
    raw = bytes(payload)
    if len(raw) > MAX_ENVELOPE_BYTES:
        _fail("payload_too_large", "$", "envelope exceeds the byte limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail("invalid_utf8", "$", "payload is not valid UTF-8")
    try:
        decoded = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_json_constant)
    except _DuplicateJsonKey:
        _fail("duplicate_json_key", "$", "duplicate JSON object key")
    except (json.JSONDecodeError, ValueError, RecursionError):
        _fail("invalid_json", "$", "payload is not valid JSON")
    return parse_envelope(decoded)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = value.astimezone(timezone.utc)
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, FrozenMapping):
        return {key: _json_value(entry) for key, entry in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        result: dict[str, Any] = {}
        for field in fields(value):
            key = "from" if isinstance(value, EnvelopeWindow) and field.name == "from_at" else field.name
            result[key] = _json_value(getattr(value, field.name))
        return result
    if isinstance(value, Mapping):
        return {str(key): _json_value(entry) for key, entry in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(entry) for entry in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite number")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return normalized, key-sorted UTF-8 JSON text without insignificant space."""

    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    """Return a prefixed SHA-256 of :func:`canonical_json`."""

    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


canonical_sha256 = canonical_hash


def canonical_payload_hash(envelope: CompanionEnvelope | Mapping[str, Any]) -> str:
    """Hash an envelope payload while excluding its transport identity field."""

    value = envelope.to_dict() if isinstance(envelope, CompanionEnvelope) else dict(envelope)
    value.pop("envelope_id", None)
    return canonical_hash(value)


def compute_envelope_id(envelope: CompanionEnvelope | Mapping[str, Any]) -> str:
    """Build the v1 retry identity defined by the producer contract."""

    if isinstance(envelope, CompanionEnvelope):
        producer_id = envelope.run.producer_id
        run_id = envelope.run.run_id
        attempt = envelope.run.attempt
    else:
        run = envelope.get("run")
        if not isinstance(run, Mapping):
            raise ValueError("envelope run is required")
        producer_id = str(run.get("producer_id", ""))
        run_id = str(run.get("run_id", ""))
        attempt = run.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int):
            raise ValueError("envelope attempt is required")
    material = f"{producer_id}\0{run_id}\0{attempt}\0{canonical_payload_hash(envelope)}"
    return "ce1:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def compute_item_id(entity_key: str | None, topic_key: str | None = None) -> str:
    """Build a stable v1 item ID from the exact provider/topic identity."""

    identity = topic_key or entity_key
    if not identity:
        raise ValueError("entity_key or topic_key is required")
    return "ci1:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _revision_field(item: CompanionItem | Mapping[str, Any], name: str) -> Any:
    if isinstance(item, CompanionItem):
        return getattr(item, name)
    return item.get(name)


def _canonical_changes(value: Any) -> list[Any]:
    if value is None:
        return []
    result: list[Any] = []
    for entry in value:
        if isinstance(entry, FieldChange):
            material = {"field": entry.field, "before": entry.before, "after": entry.after}
        elif isinstance(entry, Mapping):
            material = {"field": entry.get("field"), "before": entry.get("before"), "after": entry.get("after")}
        else:
            raise TypeError("changes must contain mappings or FieldChange values")
        result.append(_json_value(material))
    return sorted(result, key=canonical_json)


def compute_revision_key(item: CompanionItem | Mapping[str, Any]) -> str:
    """Hash only material structured state.

    Generated title/summary/action prose, observation time, provenance and input
    ordering intentionally do not influence the revision.
    """

    due_at = _revision_field(item, "due_at")
    if isinstance(due_at, str):
        due_at = _timestamp(due_at, "$.due_at")
    material = {
        "entity_key": _revision_field(item, "entity_key"),
        "topic_key": _revision_field(item, "topic_key"),
        "change": _revision_field(item, "change"),
        "severity": _revision_field(item, "severity"),
        "urgency_bucket": _revision_field(item, "urgency_bucket"),
        "due_at": due_at,
        "facts": _revision_field(item, "facts") or {},
        "changes": _canonical_changes(_revision_field(item, "changes")),
    }
    return canonical_hash(material)


def compute_delivery_key(item: CompanionItem | Mapping[str, Any], delivery_surface: str = "telegram") -> str:
    """Build the exact revision/surface delivery identity."""

    identity = _revision_field(item, "topic_key") or _revision_field(item, "entity_key")
    revision_key = _revision_field(item, "revision_key")
    if not isinstance(identity, str) or not identity:
        raise ValueError("item identity is required")
    if not isinstance(revision_key, str) or not _SHA256_ID.fullmatch(revision_key):
        raise ValueError("valid revision_key is required")
    if not isinstance(delivery_surface, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,31}", delivery_surface):
        raise ValueError("invalid delivery surface")
    material = f"{identity}\0{revision_key}\0{delivery_surface}"
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


parse_companion_envelope = parse_envelope
parse_companion_envelope_bytes = parse_envelope_bytes
revision_identity = compute_revision_key
delivery_identity = compute_delivery_key


__all__ = [
    "ActionPolicy",
    "ChangeKind",
    "CompanionEnvelope",
    "CompanionItem",
    "Completeness",
    "ContentTrust",
    "CoverageStatus",
    "EnvelopeCursor",
    "EnvelopeDelivery",
    "EnvelopeKind",
    "EnvelopeRun",
    "EnvelopeValidationError",
    "EnvelopeWindow",
    "FieldChange",
    "FrozenMapping",
    "IdentityTrust",
    "ItemTrust",
    "Provenance",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Section",
    "Severity",
    "SourceCoverage",
    "UrgencyBucket",
    "canonical_hash",
    "canonical_json",
    "canonical_payload_hash",
    "compute_delivery_key",
    "compute_envelope_id",
    "compute_item_id",
    "compute_revision_key",
    "parse_envelope",
    "parse_envelope_bytes",
]
