# Backlog TG Companion Bot

Статусы: `doing`, `review`, `todo`, `deferred`, `done`.

## Цели

- Сделать Hermes Telegram основным коротким интерфейсом задач и приёмки.
- После явного `accept` сохранять очищенный результат в правильный проект Obsidian.
- Показывать спорные результаты ночного аудита отдельными последовательными сообщениями с кнопками.
- Переносить способ взаимодействия другому пользователю Hermes One одним prompt.
- Не добавлять функции, которые не сокращают путь пользователя до результата.

## Doing

### Live nightly attention flow

Готово:

- canonical `AttentionItem` и callback model;
- последовательный dispatcher;
- durable attention state;
- adapter реального `attention_items_YYYY-MM-DD.json`;
- недельно-стабильные IDs для подавления повторного неcritical-вопроса.

Осталось:

- передать canonical items в Hermes Gateway;
- отправить только первый unresolved item;
- после выбора убрать keyboard и показать следующий;
- не выполнять выбранное файловое действие автоматически без отдельного action policy;
- провести один live smoke после подтверждения.

### Live smoke `revise` и `next`

`accept` уже проверен live. Для двух оставшихся действий проверить:

- один synthetic Hermes dispatch;
- duplicate callback не dispatch-ится повторно;
- новый итог получает новые кнопки;
- старый pending result очищается при появлении нового результата;
- real Vault остаётся неизменным.

## Review

### Real Vault accepted-result smoke

До активации нужны:

- явный `companion_project`, а не неявный `Inbox`;
- backup выбранной проектной папки;
- одна запись в `_tg-companion`;
- byte-for-byte проверка файлов `tg-context-bot` и ручного текста;
- повторный `accept` без duplicate journal entry.

Реальный Vault сейчас выключен намеренно.

## Todo

### Project routing

Определять проект до persistence. При неоднозначности предлагать короткий выбор, а не угадывать. Не писать accepted result напрямую в management block `tg-context-bot`.

### Monthly ChatGPT context intake

Подготовить отдельный import inbox и manifest для ежемесячного export. Raw import сохранять неизменным; в активный граф и project dashboards передавать только подтверждённые summaries.

### Measure interaction quality

Собирать только агрегаты без текста сообщений:

- доля результатов, принятых с первого раза;
- число доработок;
- доля лишних уточняющих вопросов;
- время от результата до решения;
- callbacks без соответствующего pending result.

## Done 2026-07-10

- Проведён полный функциональный аудит core, live bridge, Vault boundary и automation state.
- Закрыты stale callback и callback chat mismatch.
- Chat ownership добавлен в новые decision records без миграции схемы v1.
- Исправлено несовпадение `.env.example` и config keys.
- Info-сообщения больше не показывают выдуманный статус `информация` и literal `##`.
- `next` удаляет старую keyboard; `revise` ограничивает уточнение одним вопросом.
- Удалён технический UI-текст о кнопках из attention messages.
- Добавлен configurable `InteractionProfile`.
- Добавлен готовый one-prompt handoff для другого Hermes One.
- Реальный nightly report адаптируется к attention items с недельными IDs.
- Full suite: `111 passed`; Hermes completion-feedback suite: `8 passed`.

## Ранее завершено

- Reusable renderer/callback/runtime core.
- Windows-safe smoke CLI с JSON state и temp Vault.
- Multi-writer-safe `_tg-companion` persistence.
- SQLite restart recovery и callback idempotency.
- Opt-in bridge в существующем Hermes Gateway.
- Live `accept` smoke без real-Vault write.
- Ночной deterministic Git checkpoint и GitHub remote.

## Deferred

- Standalone `aiogram 3` polling bot: только если Hermes Gateway interface окажется недостаточным.
- Durable Telegram action outbox: после MVP, если post-commit delivery failures подтвердятся на практике.
- Multi-chat mode: текущий live gate остаётся single-chat.

## Не менять без отдельного подтверждения

- BotFather token, credentials и `.env`;
- live polling/restart Gateway;
- cron и Windows Task Scheduler;
- реальный Vault и ChatGPT raw import layer;
- git commit/push вне утверждённого nightly checkpoint.
