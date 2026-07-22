# Installed Hermes Gateway integration

Status date: `2026-07-21`.

The completion-feedback bridge is installed into local Hermes Agent `v0.16.0 (2026.6.5)` and active without real-Vault writes. A proactive extension is staged on disk behind a separate default-off flag; it has not been loaded by a Gateway restart or used for a Telegram send.

## Installed components

- Hermes module: `gateway/companion_bridge.py`.
- Telegram callback hook: `gateway/platforms/telegram.py`.
- Service flag: `HERMES_TG_COMPANION_ENABLED=true` in `Hermes_Gateway.cmd`.
- Local import link: `venv/Lib/site-packages/tg_companion_bot_local.pth` pointing to this repository's `src` directory.
- Durable state: `C:\Users\AIuser\AppData\Local\hermes\tg-companion\runtime.sqlite3`.

`HERMES_TG_COMPANION_OBSIDIAN_ROOT` is intentionally unset. The installed bridge persists callback state but does not write accepted results to the real Vault.

## Proactive adapter staged on 2026-07-21

- Canonical source: `integration/hermes_gateway/companion_bridge.py` plus `tg_companion_bot.hermes_proactive_worker`.
- Installed lifecycle hooks start the optional worker only after Telegram is connected and stop it before Telegram teardown. Both hooks are bounded and fail closed so completion feedback and normal disconnect remain available.
- Activation requires both the existing base bridge flag and `HERMES_TG_COMPANION_PROACTIVE_ENABLED=true`. The proactive flag is absent from `Hermes_Gateway.cmd`, so the installed extension is off by default.
- Enabling also requires a signed numeric `HERMES_TG_COMPANION_PROACTIVE_CHAT_ID`. The target chat is read only from this trusted Gateway setting; an envelope cannot override chat, markup or completion-feedback metadata.
- Spool and additive outbox tables use fixed paths under `get_hermes_home()/tg-companion`; no envelope/environment path override is accepted.
- Only an explicit retryable adapter result is automatically retried. Timeout-like ambiguous results and worker loss after the send boundary become `uncertain` and are not sent blindly again.
- The running Gateway processes were not restarted. Automation prompts/schedules, credentials, Telegram state and Vault content were not changed.

## Runtime behavior

- Existing Hermes `fb:accept/revise/next` buttons remain the user-facing keyboard.
- First callback records a durable companion decision and continues the existing Hermes synthetic user event.
- A repeated callback after in-memory state loss/restart is answered as already applied and is not dispatched to the agent twice.
- A conflicting action for an already resolved result is rejected.
- Bridge/database failure is fail-closed: the button remains for retry and no synthetic agent event is dispatched.
- Old buttons can recover after Gateway restart using Telegram chat/message id as the stable idempotency key.

## Verification

Default-off staging on `2026-07-21`:

- Canonical suite: `179 passed`; Ruff and compileall passed.
- Installed selected offline regressions: `21 passed`.
- An injected lifecycle mock proved that proactive start/stop failures remain non-fatal and that stop begins before updater/app teardown.
- Installed bridge and Telegram adapter passed `py_compile`; the bridge matches the canonical template.
- The service command contains no proactive setting, the current shell has no proactive flag, and Gateway PIDs/start times remained unchanged.
- No Telegram API call or live message was made.

Original completion-feedback acceptance on `2026-07-02`:

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

Completion-feedback backup created before the original installation:

```text
C:\AIProjects\Backups\tg-companion-hermes-integration-20260702-113450
```

Proactive default-off backup created before the 2026-07-21 staging patch:

```text
C:\AIProjects\Backups\tg-companion-proactive-default-off-20260721-174714
```

The latter contains exact pre-patch copies of `gateway/companion_bridge.py` and `gateway/platforms/telegram.py` plus their SHA-256 manifest.

Rollback consists of:

1. Stop Hermes Gateway.
2. For proactive-only rollback, restore `companion_bridge.py` and `telegram.py` from `tg-companion-proactive-default-off-20260721-174714`.
3. Run `py_compile` on both restored files.
4. Restart Gateway only under a separately approved change and confirm Telegram connectivity.

The older backup remains the recovery point for removing the entire completion-feedback integration, including `Hermes_Gateway.cmd` and `tg_companion_bot_local.pth`.

Do not delete the SQLite database during rollback unless the stored decision history has been reviewed.
