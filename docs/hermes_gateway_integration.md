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
