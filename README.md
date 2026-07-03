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
- `src/tg_companion_bot/obsidian.py` — multi-writer-safe persistence: собственный `_tg-companion` namespace, immutable event notes, idempotency, OS lock и atomic replace;
- `src/tg_companion_bot/live_adapter.py` — framework-neutral live adapter boundary: config, dry-run plan, blockers/risks без consuming updates;
- `src/tg_companion_bot/live_runtime.py` — framework-neutral runtime glue: incoming message → review render, callback → accept/revise/next, optional Obsidian persistence без polling;
- `src/tg_companion_bot/telegram_adapter_shell.py` — framework-neutral Telegram payload adapter: `RenderedMessage` → text/reply_markup/callback_data без token и polling;
- `src/tg_companion_bot/telegram_framework_adapter.py` — concrete Telegram update mapping: Telegram-like dict update → runtime message/callback → payload, без framework import, token и polling;
- `src/tg_companion_bot/smoke_cli.py` — dry-run CLI: Telegram-like JSON update → runtime → TelegramPayload JSON, callback `accept/revise/next`, state JSON и temp Obsidian persistence без token, polling и отправки;
- `src/tg_companion_bot/live_run_plan.py` — выбранный framework-кандидат и safety gates для будущего live-запуска без включения polling;
- `src/tg_companion_bot/attention_items.py` — renderer/handler для `🔴 attention_items`: отдельное сообщение, decision-кнопки, callback data и состояние после выбора без кнопок;
- `src/tg_companion_bot/hermes_gateway_adapter.py` — no-network boundary к существующему Hermes gateway: final/progress metadata, single-chat gate, callback action plans;
- `src/tg_companion_bot/state_codec.py` — единый schema-versioned codec runtime state для CLI и live bridge;
- `src/tg_companion_bot/runtime_state_store.py` — transactional SQLite state: restart recovery, rollback и сериализация конкурентных callbacks;
- `scripts/nightly_git_checkpoint.py` — deterministic secret scan → compile/tests → gated commit/push, без LLM;
- `requirements.txt` — минимальные зависимости будущего `aiogram 3` adapter shell;
- `.env.example` — шаблон локальной конфигурации без реального token;
- `docs/live_run_aiogram3.md` — dry-run runbook: token storage, polling conflict check, single-chat smoke gate;
- `tests/` — TDD-проверки поведения без Telegram token и live polling.

Цель: этот интерфейс должен легко использоваться как стартовый UX/core в других Telegram-ботах с подключёнными агентами Hermes One.

## Текущий статус

Статус обновлён: `2026-07-02`.

Проект находится на стадии проверенного dry-run MVP; live Telegram-интеграция ещё не активирована:

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
- smoke-test CLI реализован через TDD: Telegram-like JSON update → runtime → TelegramPayload JSON, callback `accept/revise/next`, `--state`, `--obsidian-root` для test vault без token/polling/sending;
- framework-кандидат выбран: `aiogram 3`, live-run safety plan реализован через TDD без запуска polling;
- install/config dry-run для `aiogram 3` подготовлен через TDD: dependency declaration, `.env.example`, runbook;
- `🔴 attention_items` handler реализован через TDD: отдельное сообщение с вариантами-кнопками и результат выбора без кнопок;
- `smoke_cli.py` интегрирован с `attention_items`: report JSON с `attention_items` превращается в последовательность Telegram-ready payloads, по одному сообщению на каждый `🔴` пункт;
- callback `attention:<id>:<option>` сохраняет решение, убирает кнопки, блокирует stale/conflicting callbacks и идемпотентно обрабатывает повтор;
- Obsidian persistence учитывает параллельный `tg-context-bot`: не изменяет daily notes, `<project>.md`, generic `_index.md` и root `Журнал решений.md`;
- accepted results сохраняются в `_tg-companion` с отдельной immutable note на `event_id`, atomic write и межпроцессной блокировкой;
- pending results и attention state могут сохраняться в SQLite вне Vault/Git и переживать перезапуск Hermes Gateway;
- persisted Hermes wrappers применяют один event внутри `BEGIN IMMEDIATE`; повторный concurrent attention callback становится `duplicate`;
- Hermes gateway boundary использует уже существующий live metadata-контракт `completion_feedback/task_final` без второго polling consumer;
- companion bridge установлен и активен в Hermes Gateway; existing `fb:*` callbacks сохраняются durable и не dispatch-ятся повторно после рестарта;
- real-Vault writes в установленном bridge пока выключены;
- single-chat live smoke `accept` прошёл через restart-fallback path: один durable decision, один Hermes dispatch, без Vault write;
- nightly Git checkpoint отделён от Obsidian-аудита и зарегистрирован в Windows Task Scheduler;
- последний запуск scheduler: `2026-07-02 03:30`, результат `0`, пропущенных запусков нет;
- локальный `main` и GitHub `origin/main` синхронизированы на `efbca13`;
- текущая проверка: `90 passed` (`2026-07-02`);
- durable callback smoke после перезапуска Gateway принят и покрыт тестом: повторный `accept` после restart видит persisted decision, не создаёт дубликат и не пишет в Obsidian при `obsidian_root=None`;
- отдельный BotFather token пока не подключён;
- отдельный polling consumer не запускался: bridge использует уже работающий Hermes Telegram polling.

## Следующий технический шаг

Следующий шаг: завершить single-chat live smoke отдельными `revise` и `next`, затем отдельной приёмкой включить одну тестовую запись в настоящий Vault.
