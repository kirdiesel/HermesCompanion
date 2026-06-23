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

### done — спроектировать минимальную архитектуру live adapter boundary

Созданы:

- `src/tg_companion_bot/live_adapter.py`
- `tests/test_live_adapter.py`

Покрыто тестами:

- загрузка config из `.env` без раскрытия token;
- missing token как blocker;
- dry-run live plan без consuming updates;
- запрет отправки сообщений без подтверждения;
- отсутствие импорта `aiogram` / Telegram framework в reusable core.

Проверка: `19 passed`.

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

### done — подготовить безопасный live runtime implementation без polling

Созданы:

- `src/tg_companion_bot/live_runtime.py`
- `tests/test_live_runtime.py`

Покрыто тестами:

- входящее сообщение превращается в итог на `🔎 приёмка` без отправки наружу;
- `accept` принимает результат, убирает pending state и при наличии `obsidian_root` пишет очищенный итог в Obsidian;
- `revise` оставляет результат pending и переводит его в `▶️ выполняется`;
- неизвестный callback безопасно превращается в noop.

Важно: это framework-neutral runtime glue. Он не запускает polling, не требует token, не импортирует Telegram framework и может быть подключён к разным адаптерам.

Проверка: `23 passed`.

### done — подготовить Telegram framework adapter shell

Созданы:

- `src/tg_companion_bot/telegram_adapter_shell.py`
- `tests/test_telegram_adapter_shell.py`

Покрыто тестами:

- conversion `RenderedMessage` → framework-neutral Telegram payload;
- inline keyboard `reply_markup` из кнопок приёмки;
- callback data namespace `companion:<action>:<result_id>`;
- запрет неподдерживаемых callback action;
- защита лимита Telegram callback data 64 bytes;
- промежуточные сообщения без `reply_markup`.

Важно: shell не запускает polling, не требует token и не привязан к конкретному Telegram framework.

Проверка: `27 passed`.

### done — подготовить concrete Telegram framework adapter implementation

Созданы:

- `src/tg_companion_bot/telegram_framework_adapter.py`
- `tests/test_telegram_framework_adapter.py`

Покрыто тестами:

- Telegram-like text message update → framework-neutral runtime message;
- runtime result → Telegram payload без фактической отправки;
- callback query update → framework-neutral callback object;
- отклонение non-text/missing message и неизвестных callback namespace;
- явные флаги `consumes_updates=False` и `sends_immediately=False`.

Важно: adapter implementation пока не импортирует `aiogram`/`python-telegram-bot`, не требует token, не запускает polling и не consuming updates.

Проверка: `32 passed`.

### done — подготовить smoke-test CLI для dry-run update mapping

Созданы:

- `src/tg_companion_bot/smoke_cli.py`
- `tests/test_smoke_cli.py`

Покрыто тестами:

- CLI принимает Telegram-like JSON update из stdin;
- CLI принимает update из файла через `--input`;
- update прогоняется через adapter implementation → runtime → TelegramPayload JSON;
- output содержит safety-флаги `requires_token=False`, `consumes_updates=False`, `sends_messages=False`;
- unsupported update отклоняется без consuming/sending.

Важно: CLI не требует BotFather token, не запускает polling и не отправляет реальные Telegram-сообщения.

Проверка: `35 passed`.

### todo — выбрать framework-кандидат и описать безопасный live-run plan

Перед реальным запуском live polling:

- сравнить `aiogram 3` и `python-telegram-bot` для текущей adapter boundary;
- выбрать framework-кандидат для минимального live shell;
- описать token storage без попадания token в git;
- описать polling conflict check;
- описать dry-run smoke перед consuming updates;
- проверить отдельный BotFather token;
- убедиться, что token не используется Hermes Gateway;
- исключить другого polling consumer;
- описать stop/restart процесса;

### todo — ночное git-обновление проекта

В обычные рабочие шаги git commit/push не выполнять. Git update проекта (`status` → tests → commit → push при наличии remote/auth) выполняет только nightly Obsidian optimizer. Если тесты падают, remote не настроен или изменения рискованные — вынести отчёт в `🔎 приёмка`.

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
