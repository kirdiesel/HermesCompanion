# TG Companion Bot

Назначение: бот-собеседник и главный интерфейс общения с Hermes.

## Цель

Создать Telegram-бота, который общается с Кириллом через Hermes, помогает принимать результаты, задаёт уточняющие вопросы, предлагает кнопки и постепенно становится главным интерфейсом работы с ИИ.

Базовый цикл:

```text
сообщение в Telegram → проверяемый результат → приёмка кнопкой → Obsidian → следующий оптимальный шаг
```

## Ключевые функции

- живое общение;
- итоговые ответы с оптимальным количеством кнопок;
- приёмка результата;
- доработка результата;
- предложение следующего шага;
- ночная оптимизация структуры Obsidian;
- управление взаимодействием с личными и рабочими агентами.

## Согласованные пользовательские статусы

Использовать только:

- `▶️ выполняется`
- `🔎 приёмка`
- `✅ готово`

## Согласованные правила кнопок

- Кнопки нужны на итоговом результате и приёмке.
- Кнопки не нужны на промежуточных комментариях, статусах, системных сообщениях и простых информационных ответах.
- Количество кнопок зависит от ситуации.
- Labels должны быть смысловыми действиями.
- После подтверждения бот выполняет рекомендацию, а если её нет — следующий оптимальный шаг.

## Проектные документы

- `PROJECT_CONTEXT.md` — исходный контекст проекта и согласованные правила.
- `HERMES_BRIEF.md` — бриф для Hermes/агентов.
- `AGENT_MANIFEST.md` — манифест агента проекта.
- `BACKLOG.md` — нерешённые задачи и следующий порядок реализации.

## Связанный проект Obsidian

`C:\AIProjects\Obsidian\One\03_Проекты\Активные\01_TG_бот_собеседник.md`

## Reusable interface core

Первый слой реализации делается как переносимое ядро интерфейса, а не как одноразовый live-бот:

- `src/tg_companion_bot/rendering.py` — renderer статусов, итоговых сообщений и кнопок;
- `src/tg_companion_bot/callbacks.py` — callback-модель `accept/revise/next`;
- `src/tg_companion_bot/obsidian.py` — persistence layer для записи принятого результата в проектную заметку и журнал решений;
- `src/tg_companion_bot/live_adapter.py` — framework-neutral live adapter boundary: config, dry-run plan, blockers/risks без consuming updates;
- `src/tg_companion_bot/live_runtime.py` — framework-neutral runtime glue: incoming message → review render, callback → accept/revise/next, optional Obsidian persistence без polling;
- `src/tg_companion_bot/telegram_adapter_shell.py` — framework-neutral Telegram payload adapter: `RenderedMessage` → text/reply_markup/callback_data без token и polling;
- `src/tg_companion_bot/telegram_framework_adapter.py` — concrete Telegram update mapping: Telegram-like dict update → runtime message/callback → payload, без framework import, token и polling;
- `src/tg_companion_bot/smoke_cli.py` — dry-run CLI: Telegram-like JSON update → runtime → TelegramPayload JSON без token, polling и отправки;
- `tests/` — TDD-проверки поведения без Telegram token и live polling.

Цель: этот интерфейс должен легко использоваться как стартовый UX/core в других Telegram-ботах с подключёнными агентами Hermes One.

## Текущий статус

Проект находится на ранней стадии MVP:

- локальный git-репозиторий создан;
- контекст перенесён;
- бриф создан;
- манифест агента создан;
- backlog создан;
- renderer итогового сообщения и кнопок реализован через TDD;
- callback-модель `accept/revise/next` реализована через TDD;
- Obsidian persistence MVP реализован через TDD;
- live adapter boundary реализован через TDD в dry-run режиме;
- live runtime glue реализован через TDD без polling/token;
- Telegram adapter shell реализован через TDD без token/polling: conversion `RenderedMessage` → Telegram payload/callback data;
- concrete Telegram framework adapter mapping реализован через TDD без token/polling;
- smoke-test CLI реализован через TDD: Telegram-like JSON update → runtime → TelegramPayload JSON без token/polling/sending;
- текущая проверка: `35 passed`;
- git commit/push обычными дневными шагами не выполняется — git update проекта делает nightly Obsidian optimizer;
- отдельный BotFather token пока не подключён;
- live polling пока не запускался.

## Следующий технический шаг

Следующий шаг: выбрать Telegram framework-кандидат (`aiogram 3` или `python-telegram-bot`) и описать безопасный live-run plan: token storage, polling conflict check, dry-run smoke before consuming updates.
