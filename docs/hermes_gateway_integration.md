# Hermes gateway integration boundary

The installed Hermes Telegram gateway already owns polling and implements semantic final-result buttons through metadata:

```python
{
    "completion_feedback": True,
    "task_final": True,
    "suppress_completion_feedback": False,
}
```

`hermes_gateway_adapter.py` prepares action plans matching that contract. It never imports the installed Hermes runtime, accesses credentials, sends messages, or starts polling.

For restart-safe state, the bridge should call `plan_persisted_hermes_event(...)` with `SQLiteRuntimeStateStore`; see `runtime_state_store.md`. The wrapper serializes concurrent callbacks and commits state before returning actions.

## Integration rule

- Final result: call the existing Hermes `send(...)` path with the metadata above. Hermes creates its `fb:accept/revise/next` keyboard.
- Progress/status: set `suppress_completion_feedback=True`.
- Companion or attention decision: execute the returned `answer_callback` and `edit_message` actions; the edit action has no reply markup.
- Attention item: the bridge must support the action's explicit `reply_markup`. Do not create a second polling process.

The approved local installation and completed live `accept` smoke are documented in `hermes_gateway_installation.md`. Remaining live `revise`/`next` checks and real-Vault writes are separate approval gates.

## Nightly attention boundary

`nightly_attention_adapter.py` now accepts the actual list-shaped `attention_items_YYYY-MM-DD.json` produced by the 03:00 audit and converts it to canonical `AttentionItem` values. IDs are stable within an ISO week, so a resolved noncritical issue is not re-presented every night.

The adapter is dry-run only: it reads no token and sends nothing. Live delivery still requires an explicit Gateway executor that:

1. persists all current items with `plan_persisted_attention_item(...)`;
2. sends only the first unresolved item;
3. handles `attention:*` callbacks through the durable store;
4. edits the selected message without a keyboard;
5. sends the next unresolved item;
6. records the decision but does not execute a filesystem change unless a separate action policy allows it.
