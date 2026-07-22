# Proactive Companion foundation — phase 0

This phase provides a local, network-free foundation for the planned morning brief and follow-up delta. It is intentionally not wired into the installed Hermes Gateway or Telegram.

## Data flow available in the canonical repository

```text
UTF-8 CompanionEnvelope v1
  -> strict validation
  -> atomic local spool claim
  -> SQLite intake + exact entity revisions
  -> deterministic merge and Russian rendering
  -> durable outbox
  -> injected fake sender
```

The envelope cannot select a Telegram chat, token, local action path or tool. Mail and calendar content is treated as untrusted display data. Informational deliveries always set `suppress_completion_feedback=True` and carry no reply markup.

## Modules

- `companion_envelope.py` — frozen v1 models, bounded UTF-8/JSON parsing, trust/TTL/content checks and canonical identities.
- `proactive_runtime.py` — exact identity merge, coverage warnings, noise budget and safe plain-text rendering.
- `delivery_outbox.py` — additive SQLite intake/revision/batch/outbox tables, atomic spool primitives and network-free worker state machine.
- `proactive_pipeline.py` — validates and stages spool envelopes, closes one deterministic batch and enqueues one neutral action or a durable no-op.

## Delivery safety model

- Duplicate envelope, entity revision, batch close and delivery keys are idempotent.
- A lease lost before `begin_send` is retryable.
- `begin_send` marks the ambiguity boundary. A worker lost after that boundary becomes `uncertain` and is not automatically retried.
- Only a sender-classified definite failure enters retry state.
- A successful fake/live adapter must persist the returned message ID before a row becomes `sent`.
- Expired morning/delta actions are never sent late.

Telegram does not expose a client idempotency key, so strict exactly-once delivery cannot be promised after an ambiguous acknowledgement. This design explicitly prefers suppressing an uncertain duplicate over a blind resend.

## Local verification

```powershell
python -m pytest tests\test_companion_envelope.py tests\test_proactive_runtime.py tests\test_delivery_outbox.py tests\test_proactive_pipeline.py -q
python -m pytest -q
```

All tests use temporary directories, temporary SQLite files and injected fake senders.

## Not enabled in phase 0

- installed Hermes Gateway changes;
- Telegram send or callback handling;
- automation schedule/prompt changes;
- Yandex credential or IMAP changes;
- Windows task changes;
- real Obsidian Vault writes;
- external mail/calendar actions.

The next gate is a source review plus an approved installed-Gateway patch behind a default-off feature flag. A live one-chat smoke, restart and schedule changes remain separate approvals.
