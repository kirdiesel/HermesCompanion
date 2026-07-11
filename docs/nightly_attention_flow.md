# Nightly attention flow

## Input

The deterministic 03:00 audit writes:

```text
...\Отчёты ночной оптимизации Obsidian\attention_items_YYYY-MM-DD.json
```

The current file is a JSON list with `type`, `title`, `detail` and Russian option labels. It is not the canonical companion schema.

## Dry run

```powershell
python -m tg_companion_bot.nightly_attention_adapter `
  --input "<attention_items file>" `
  --chat-id "<allowed chat>"
```

Output includes canonical items and Telegram-ready payloads. Safety flags remain:

```json
{"requires_token": false, "consumes_updates": false, "sends_messages": false}
```

## Repeat policy

Noncritical item IDs use the ISO year/week plus issue type and title. Count changes during the same week do not create a new prompt. A new week creates a new review item. Critical alerts need a separate severity field before they can bypass this policy.

## Live activation gate

- Back up the installed Hermes bridge files.
- Keep real-Vault writes disabled.
- Persist items before attempting Telegram send.
- Deliver one item at a time.
- Authorize callback user/chat through the existing Gateway policy.
- A decision records intent only; it must not directly rename, move or delete Vault files.
- Verify duplicate callback, Gateway restart and failed-send behavior.
- Restart Gateway and send the first real item only after explicit confirmation.
