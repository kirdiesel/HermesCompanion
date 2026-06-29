# aiogram 3 live-run dry-run plan

This runbook prepares a future `aiogram 3` Telegram adapter without starting live polling.

## Current mode

- Mode: dry-run.
- No BotFather token is required for tests or `smoke_cli`.
- No consuming updates.
- No real Telegram messages are sent.

## Token storage

1. Create a separate BotFather token only after explicit user confirmation.
2. Copy `.env.example` to `.env` locally.
3. Put the real token into `TG_COMPANION_BOT_TOKEN` in `.env` only.
4. Do not commit `.env`.
5. Do not paste the token into README, tests, logs, Obsidian, Telegram, or GitHub.

## Polling conflict check

Before any live polling:

1. Confirm this token is not used by Hermes Gateway.
2. Confirm no other process consumes updates for the same bot token.
3. Confirm the smoke CLI output is correct.
4. Confirm the target chat id is explicitly allowed by `TG_COMPANION_ALLOWED_CHAT_ID`.

## Dry-run smoke before live mode

Run from project root:

```bash
python -m tg_companion_bot.smoke_cli --input examples/telegram_message_update.json
```

The output must include:

- `ok: true`
- `mode: dry_run`
- `requires_token: false`
- `consumes_updates: false`
- `sends_messages: false`
- a Telegram payload with `chat_id`, text, and review buttons.

## Single-chat smoke gate

Only after explicit confirmation and token setup:

1. Start with one allowed chat id.
2. Send one test message.
3. Verify the result appears in `🔎 приёмка`.
4. Verify intermediate messages have no acceptance keyboard.
5. Verify `accept/revise/next` callbacks.
6. Stop the bot after the test.

## Prohibited before confirmation

- Do not start polling.
- Do not start webhook mode.
- Do not send real Telegram messages.
- Do not commit `.env`.
- Do not reuse Hermes Gateway token.
