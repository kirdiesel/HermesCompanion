# Installed Hermes Gateway integration

Status date: `2026-07-02`.

The optional companion bridge is installed into local Hermes Agent `v0.16.0 (2026.6.5)` and activated without real-Vault writes.

## Installed components

- Hermes module: `gateway/companion_bridge.py`.
- Telegram callback hook: `gateway/platforms/telegram.py`.
- Service flag: `HERMES_TG_COMPANION_ENABLED=true` in `Hermes_Gateway.cmd`.
- Local import link: `venv/Lib/site-packages/tg_companion_bot_local.pth` pointing to this repository's `src` directory.
- Durable state: `C:\Users\AIuser\AppData\Local\hermes\tg-companion\runtime.sqlite3`.

`HERMES_TG_COMPANION_OBSIDIAN_ROOT` is intentionally unset. The installed bridge persists callback state but does not write accepted results to the real Vault.

## Runtime behavior

- Existing Hermes `fb:accept/revise/next` buttons remain the user-facing keyboard.
- First callback records a durable companion decision and continues the existing Hermes synthetic user event.
- A repeated callback after in-memory state loss/restart is answered as already applied and is not dispatched to the agent twice.
- A conflicting action for an already resolved result is rejected.
- Bridge/database failure is fail-closed: the button remains for retry and no synthetic agent event is dispatched.
- Old buttons can recover after Gateway restart using Telegram chat/message id as the stable idempotency key.

## Verification

- Companion suite: `90 passed`.
- Hermes completion-feedback suite: `8 passed`.
- Hermes thread fallback suite: `46 passed` in isolation.
- Hermes model picker suite: `6 passed` in isolation.
- Hermes overflow suite: `4 passed` in isolation.
- `py_compile` passed for the bridge and Telegram adapter.
- Gateway restarted cleanly and Telegram polling reconnected.
- Bridge startup log reports `real Vault writes: False`.

## Live smoke result

On `2026-07-02` one approved single-chat smoke message was sent without registering in-memory feedback state, which exercised the restart-recovery path.

- User selected `accept`.
- SQLite revision changed from `0` to `1`.
- Exactly one durable decision was stored and pending results returned to zero.
- Gateway dispatched one synthetic Hermes reply referencing the smoke message.
- Real Vault `_tg-companion` directory count remained zero.
- No companion persistence or dispatch error was logged.

Live `revise` and `next` paths remain unexecuted; they are covered by automated tests and require separate user interactions for live acceptance.

The combined collection of several legacy Telegram fake-module suites has three order-dependent group-routing failures; each affected suite passes in isolation. No routing code was changed to mask that pre-existing test-isolation defect.

## Backup and rollback

Backup created before installation:

```text
C:\AIProjects\Backups\tg-companion-hermes-integration-20260702-113450
```

Rollback consists of:

1. Stop Hermes Gateway.
2. Restore `telegram.py` and `Hermes_Gateway.cmd` from the backup.
3. Remove `gateway/companion_bridge.py` and `tg_companion_bot_local.pth`.
4. Restart Gateway and confirm Telegram connectivity.

Do not delete the SQLite database during rollback unless the stored decision history has been reviewed.
