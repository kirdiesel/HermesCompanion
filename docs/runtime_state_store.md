# Durable runtime state

The live Hermes bridge must not keep `RuntimeState` only in process memory. `SQLiteRuntimeStateStore` persists pending results, pending attention items, and resolved attention decisions across Gateway restarts.

## Storage location

Use a local path outside the Obsidian Vault and outside Git, for example:

```text
C:\Users\<user>\AppData\Local\hermes\tg-companion\runtime.sqlite3
```

The database contains no Telegram token or model credential. It stores only minimal pending summaries and decision state already required by the interface.

## Transaction rule

Use `plan_persisted_hermes_event(...)` or `plan_persisted_attention_item(...)`:

```python
store = SQLiteRuntimeStateStore(runtime_db_path)
plan = plan_persisted_hermes_event(
    event,
    store=store,
    allowed_chat_id=allowed_chat_id,
    allowed_user_id=allowed_user_id,
    obsidian_root=approved_obsidian_root,
)
```

The wrapper:

1. starts SQLite `BEGIN IMMEDIATE`;
2. loads and validates schema-versioned state;
3. applies one event;
4. commits only when state changed;
5. returns the Hermes action plan after the commit.

This serializes concurrent callbacks. A second identical attention callback observes the first committed decision and becomes `duplicate` instead of applying twice.

## Failure behavior

- Handler exception rolls back the state transaction.
- Unauthorized/no-op events do not increment the state revision.
- WAL and SQLite busy timeout handle short concurrent access.
- Invalid schema or database failures raise `RuntimeStateStoreError` and must stop action execution.

## Remaining delivery risk

State is committed before Telegram actions are executed. If Telegram fails after commit, the state remains correct but the UI action may need retry. A durable action outbox is a later reliability enhancement; it is not implemented in this dry-run boundary.

## Activation checks

1. Resolve a database path outside Vault/Git.
2. Confirm file ACLs are limited to the local user.
3. Start with one allowed chat/user.
4. Create a pending result, restart Gateway, and verify it remains actionable.
5. Run two identical callbacks and verify one `applied` plus one `duplicate`.
6. Back up the database before schema migrations.

This module does not start polling, access credentials, or modify the installed Hermes Gateway.
