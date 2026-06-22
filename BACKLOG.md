# Backlog TG Companion Bot

## Статусы

- `todo` — не начато
- `doing` — в работе
- `review` — требуется приёмка Кирилла
- `done` — принято/закрыто

## Закрыто в текущем подготовительном цикле

### done — перенести исходный контекст проекта

Созданы:

- `PROJECT_CONTEXT.md`
- `HERMES_BRIEF.md`
- `AGENT_MANIFEST.md`
- `BACKLOG.md`

### done — создать бриф для Hermes

Бриф создан в `HERMES_BRIEF.md`.

### done — создать манифест агента проекта

Манифест создан в `AGENT_MANIFEST.md`.

## Ближайшие нерешённые задачи


### doing — сделать интерфейс переносимым стартовым шаблоном

Созданный интерфейс бота должен легко переноситься как стартовый UX/core в другие Telegram-боты с подключенными агентами Hermes One.

Критерии:

- renderer, callback model и статусы не зависят от live Telegram token;
- agent-specific routing отделён от базового интерфейса;
- labels/кнопки можно конфигурировать;
- новый бот может использовать этот пакет как starter interface без копипасты всей реализации.

### done — выбрать технический стек MVP для первого слоя

Выбран безопасный первый слой: Python `src/` package с domain-renderer-ами, которые тестируются без Telegram token и без live polling.

Framework для live Telegram adapter (`aiogram 3` или `python-telegram-bot`) остаётся отдельным решением перед подключением BotFather token.

### todo — спроектировать минимальную архитектуру

Нужно описать:

- entrypoint;
- config loading;
- handlers;
- callback router;
- renderers;
- Obsidian writer;
- storage/state;
- tests.

### done — создать TDD-первый renderer итогового сообщения

Созданы:

- `src/tg_companion_bot/rendering.py`
- `tests/test_rendering.py`
- `pytest.ini`

Покрыто тестами:

- итоговый текст;
- статусы `▶️`, `🔎`, `✅`;
- отсутствие кнопок для промежуточных сообщений;
- кнопки для приёмки результата;
- смысловые labels.

Проверка: `4 passed`.

### done — создать callback model

Созданы:

- `src/tg_companion_bot/callbacks.py`
- `tests/test_callbacks.py`

Поддержаны действия:

- `accept` — принять результат и перейти к рекомендации / оптимальному следующему шагу;
- `revise` — отправить на доработку без перевода в готово;
- `next` — показать следующий шаг, оставляя задачу на приёмке.

Callback-модель сделана framework-agnostic, чтобы её можно было переносить в другие Telegram-боты с агентами Hermes One.

Проверка: `11 passed`.

### done — создать Obsidian persistence MVP

Созданы:

- `src/tg_companion_bot/obsidian.py`
- `tests/test_obsidian_persistence.py`

После принятия результата persistence layer пишет очищенный итог в:

- проектную заметку `_index.md`;
- `Журнал решений.md`;
- следующий шаг;
- список артефактов.

Важно: слой не пишет сырую переписку и не зависит от live Telegram token/framework.

Проверка: `14 passed`.

### todo — подготовить безопасный live-run plan

Перед запуском live polling проверить:

- есть ли отдельный BotFather token;
- не используется ли этот token Hermes Gateway;
- нет ли другого polling consumer;
- как остановить bot process;
- как smoke-test message rendering без consuming updates.

### todo — создать отдельный Telegram-бот через BotFather

Требует участия/подтверждения Кирилла. Не выполнять автоматически.

## Не трогать без подтверждения

- credentials;
- `.env` с токенами;
- BotFather настройки;
- live polling;
- git commit;
- cron schedules;
- массовую перестройку Obsidian.
