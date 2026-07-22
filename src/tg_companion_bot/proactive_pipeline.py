from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .companion_envelope import (
    CompanionEnvelope,
    EnvelopeValidationError,
    canonical_hash,
    canonical_json,
    parse_envelope,
    parse_envelope_bytes,
)
from .delivery_outbox import (
    BatchEnqueueResult,
    DeliveryCandidate,
    EntityRevision,
    IngestResult,
    IntakeEvent,
    SQLiteDeliveryOutbox,
    SpoolLayout,
    SpoolProcessResult,
    SpoolValidationError,
    process_spool_once,
)
from .proactive_runtime import plan_proactive_delivery


class ProactivePipelineError(RuntimeError):
    """Raised when a validated proactive batch cannot be safely planned."""


@dataclass(frozen=True)
class EnvelopeIngestResult:
    envelope: CompanionEnvelope
    persistence: IngestResult


def ingest_envelope_bytes(
    payload: bytes,
    *,
    store: SQLiteDeliveryOutbox,
    now: datetime | None = None,
) -> EnvelopeIngestResult:
    """Validate and durably stage one envelope without planning a live target."""

    envelope = parse_envelope_bytes(payload)
    persistence = store.ingest(
        _intake_event(envelope),
        revisions=tuple(_entity_revision(item) for item in envelope.items),
        now=now,
    )
    return EnvelopeIngestResult(envelope=envelope, persistence=persistence)


def process_proactive_spool_once(
    layout: SpoolLayout,
    *,
    store: SQLiteDeliveryOutbox,
    now: datetime | None = None,
) -> SpoolProcessResult:
    """Process one completed spool file and quarantine only safe validation codes."""

    def processor(payload: bytes) -> None:
        try:
            ingest_envelope_bytes(payload, store=store, now=now)
        except EnvelopeValidationError as error:
            raise SpoolValidationError(_safe_validation_code(error.code)) from error

    return process_spool_once(layout, processor)


def close_proactive_batch(
    batch_key: str,
    *,
    store: SQLiteDeliveryOutbox,
    now: datetime | None = None,
) -> BatchEnqueueResult:
    """Merge all persisted members and atomically close one informational batch."""

    payloads = store.batch_payloads(batch_key)
    if not payloads:
        raise ProactivePipelineError("Cannot close an empty proactive batch")
    try:
        envelopes = tuple(parse_envelope(payload) for payload in payloads)
    except EnvelopeValidationError as error:
        raise ProactivePipelineError(f"Stored envelope is invalid: {error.code}") from error
    if any(envelope.delivery.batch_key != batch_key for envelope in envelopes):
        raise ProactivePipelineError("Stored envelope batch key mismatch")

    action = plan_proactive_delivery(envelopes, now=now)
    batch_hash = _batch_hash(envelopes)
    deliveries: tuple[DeliveryCandidate, ...] = ()
    if action is not None:
        action_payload: dict[str, Any] = {
            "text": action.text,
            "metadata": dict(action.metadata),
            "reply_markup": action.reply_markup,
        }
        deliveries = (
            DeliveryCandidate(
                delivery_key=_batch_delivery_key(batch_key, action_payload),
                action_kind=action.kind,
                payload=action_payload,
                available_at=max(envelope.delivery.not_before for envelope in envelopes),
                expires_at=min(envelope.delivery.expires_at for envelope in envelopes),
            ),
        )
    return store.enqueue_batch(
        batch_key=batch_key,
        content_hash=batch_hash,
        deliveries=deliveries,
        now=now,
    )


def _intake_event(envelope: CompanionEnvelope) -> IntakeEvent:
    return IntakeEvent(
        envelope_id=envelope.envelope_id,
        dedupe_key=(
            f"{envelope.run.producer_id}:{envelope.run.run_id}:attempt-{envelope.run.attempt}"
        ),
        content_hash=envelope.canonical_hash(),
        source=envelope.run.producer_id,
        kind=envelope.run.kind.value,
        generated_at=envelope.run.completed_at,
        payload=envelope.to_dict(),
        batch_key=envelope.delivery.batch_key,
    )


def _entity_revision(item: Any) -> EntityRevision:
    identity = item.entity_key or item.topic_key or item.item_id
    payload = json.loads(canonical_json(item))
    return EntityRevision(
        entity_key=identity,
        topic_key=item.topic_key,
        revision_key=item.revision_key,
        observed_at=item.observed_at,
        payload=payload,
    )


def _batch_hash(envelopes: tuple[CompanionEnvelope, ...]) -> str:
    members = sorted(envelope.canonical_hash() for envelope in envelopes)
    return canonical_hash({"members": members})


def _batch_delivery_key(batch_key: str, payload: dict[str, Any]) -> str:
    material = canonical_json({"batch_key": batch_key, "surface": "telegram", "payload": payload})
    return "batch1:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _safe_validation_code(code: str) -> str:
    normalized = "".join(character if character.isalnum() else "_" for character in code.casefold())
    normalized = "_".join(part for part in normalized.split("_") if part)
    if not normalized or not normalized[0].isalpha():
        return "invalid_envelope"
    return normalized[:64]
