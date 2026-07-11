# TG Companion Bot

Telegram-интерфейс для цикла:

```text
задача -> результат -> приёмка -> Obsidian -> следующий шаг
```

Проект развивает переносимое интерфейсное ядро и подключает его к уже работающему Hermes Telegram Gateway. Отдельный polling-процесс сейчас не нужен и не запущен.

## Что работает сейчас

- Hermes Gateway принимает обычные Telegram-сообщения и выполняет задачи.
- Итоговые ответы получают смысловые кнопки `Принять результат`, `Доработать`, `Следующий шаг`.
- Промежуточные, системные, cron- и диагностические сообщения не получают кнопки приёмки.
- `accept/revise/next` превращаются в следующий Hermes-turn.
- `accept` проверен live; решения сохраняются в SQLite и переживают перезапуск Gateway.
- Повторный callback не запускает действие второй раз; callback другого чата отклоняется.
- Dry-run цикл message/callback/state/temporary Obsidian покрыт тестами.
- Запись в общий Vault изолирована в `03_Проекты/Активные/<project>/_tg-companion` и защищена lock + atomic replace.
- Реальный nightly Obsidian report преобразуется в Telegram-ready attention items без token и отправки.
- Интерфейсный профиль и готовый prompt для переноса в другой Hermes One вынесены отдельно.
- Ночной Git checkpoint проверяет секреты, компиляцию и тесты, затем при необходимости commit/push.

## Что пока не работает live

- Реальные nightly attention items ещё не отправляются в Telegram с кнопками.
- `revise` и `next` не прошли отдельный live smoke после установки durable bridge.
- Accepted results не пишутся в реальный Vault: `HERMES_TG_COMPANION_OBSIDIAN_ROOT` не задан.
- Надёжная маршрутизация результата в конкретный проект отсутствует; fallback остаётся `Inbox`.
- Ежемесячный ChatGPT export пока передаётся и импортируется вручную.
- Standalone `aiogram`-бот не реализован; это отложенный reference adapter, а не текущий runtime.

## Важное разграничение

Ночная оптимизация Obsidian выполняется внешними Hermes-задачами:

- `nightly-obsidian-structure-optimizer` в 03:00: локальный детерминированный аудит;
- `nightly-obsidian-semantic-review` в 03:30: необязательный AI-обзор.

`tg-companion-bot` не оптимизирует Vault сам. Его роль в этом контуре: превратить спорные пункты аудита в короткие Telegram-решения с кнопками и сохранить выбор.

## Пользовательские правила

Статусы только:

- `▶️ выполняется`
- `🔎 приёмка`
- `✅ готово`

Кнопки:

- только под итогом или реальным выбором;
- минимально достаточное число;
- без кнопок под прогрессом, справкой, ошибкой и системным сообщением;
- `next` не означает приёмку;
- `accept` обязателен перед записью результата как принятого.

Краткость:

- сначала результат;
- затем только проверка, риск и следующий шаг, влияющие на решение;
- не описывать пользователю устройство кнопок, state или adapter-а.

## Основные модули

- `interaction_profile.py`: статусы, labels, доступные действия и переносимый handoff prompt.
- `rendering.py`: краткие итоговые/progress/info сообщения.
- `callbacks.py`: `accept/revise/next` без Telegram framework.
- `live_runtime.py`: pending state, ownership, idempotency и Obsidian handoff.
- `runtime_state_store.py`: restart-safe SQLite transactions.
- `hermes_gateway_adapter.py`: boundary к существующему Hermes Gateway.
- `obsidian.py`: multi-writer-safe accepted-result persistence.
- `attention_items.py`: один спорный пункт и его decision buttons.
- `attention_dispatcher.py`: последовательная выдача attention items.
- `nightly_attention_adapter.py`: реальный nightly JSON -> canonical attention items.
- `smoke_cli.py`: Windows-safe end-to-end dry-run без token/polling/send.
- `scripts/nightly_git_checkpoint.py`: deterministic nightly Git flow.

## Перенос интерфейса

Готовый prompt находится в `docs/hermes_one_interface_prompt.md` и выводится командой:

```powershell
python -m tg_companion_bot.interaction_profile
```

Renderer принимает другой `InteractionProfile`, поэтому labels можно заменить без копирования callback/runtime-кода.

## Проверка

```powershell
python -m compileall -q src scripts
python -m pytest -q
```

Проверено 10 июля 2026 года:

```text
111 passed
Hermes Gateway completion-feedback: 8 passed
```

Dry-run реального ночного отчёта:

```powershell
python -m tg_companion_bot.nightly_attention_adapter `
  --input "C:\AIProjects\Obsidian\One\Проекты\Жизнь\Отчёты ночной оптимизации Obsidian\attention_items_2026-07-10.json" `
  --chat-id 378157839
```

Команда не читает token, не consuming updates и не отправляет сообщения.

## Следующий шаг

Подключить output `nightly_attention_adapter` к установленному Hermes Gateway action executor с durable state и последовательной выдачей одного пункта. Активацию реальной отправки и restart Gateway выполнять отдельным подтверждённым шагом.
