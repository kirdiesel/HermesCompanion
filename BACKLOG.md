# Backlog TG Companion Bot

## Статусы

- `todo` — не начато
- `doing` — в работе
- `review` — требуется приёмка владельца продукта
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

Framework-кандидат для live Telegram adapter уже выбран отдельным шагом: `aiogram 3`. BotFather token и live polling остаются отдельными подтверждаемыми действиями.

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

Первоначальный MVP писал очищенный итог в generic project files:

- проектную заметку `_index.md`;
- `Журнал решений.md`;
- следующий шаг;
- список артефактов.

Важно: слой не пишет сырую переписку и не зависит от live Telegram token/framework.

Этот layout впоследствии заменён multi-writer-safe namespace, описанным следующим пунктом.

Проверка: `14 passed`.

### done — защитить Obsidian persistence для общего Vault с несколькими писателями

После аудита работающего `tg-context-bot` companion persistence перенесён в собственный namespace `03_Проекты/Активные/<project>/_tg-companion`. Generic project files больше не перезаписываются.

Реализовано:

- immutable decision note на каждый `event_id`;
- идемпотентный повтор события и конфликт при повторном id с другим содержимым;
- системная межпроцессная блокировка Windows;
- атомарная замена Markdown-файлов;
- конкурентные тесты 20 threads и 6 отдельных Python processes без потери событий;
- сохранность daily notes, context-bot project note, generic `_index.md` и root `Журнал решений.md`;
- контракт `docs/vault_multi_writer_contract.md`.

Проверка: `90 passed`.

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

### done — подготовить smoke-test CLI для полного dry-run callback pipeline

Созданы:

- `src/tg_companion_bot/smoke_cli.py`
- `tests/test_smoke_cli.py`

Покрыто тестами:

- CLI принимает Telegram-like JSON update из stdin;
- CLI принимает update из файла через `--input`;
- update прогоняется через adapter implementation → runtime → TelegramPayload JSON;
- Windows-safe JSON output не падает на русском тексте и emoji в консоли cp1251;
- `--state` сохраняет pending result после message update;
- callback `accept` переводит результат в `✅ готово`, убирает pending state и снимает inline keyboard;
- callback `revise` переводит результат в `▶️ выполняется` и оставляет pending state;
- callback `next` оставляет результат на `🔎 приёмка` и оставляет pending state;
- `--obsidian-root` пишет принятый результат только в test vault через существующий persistence layer;
- повреждённый state file возвращает понятную ошибку `invalid_state`;
- output содержит safety-флаги `requires_token=False`, `consumes_updates=False`, `sends_messages=False`;
- unsupported update отклоняется без consuming/sending.

Важно: CLI не требует BotFather token, не запускает polling и не отправляет реальные Telegram-сообщения.

Проверка: `49 passed`.

Следующий шаг из исходного smoke CLI ТЗ — выбрать live Telegram framework и подготовить безопасный live-run plan — уже закрыт в текущем цикле: выбран `aiogram 3`, safety plan и config dry-run описаны ниже. Поэтому актуальный следующий технический шаг остаётся `aiogram 3` adapter skeleton без BotFather token и live polling.

### done — выбрать framework-кандидат и описать безопасный live-run plan

Созданы:

- `src/tg_companion_bot/live_run_plan.py`
- `tests/test_live_run_plan.py`

Выбор:

- framework-кандидат: `aiogram 3`;
- причина: async handlers, inline keyboards, callback queries, polling/webhook support, тонкий adapter вокруг framework-neutral core.

Safety plan до live polling:

- режим по умолчанию: `dry_run`;
- `consumes_updates=False`;
- `sends_messages=False`;
- requires explicit user confirmation;
- requires BotFather token outside git;
- activation gates: all tests green, explicit confirmation, token outside git, no polling conflict, dry-run payload verified, single-chat limited smoke.

Проверка: `38 passed`.

### done — подготовить install/config dry-run для `aiogram 3`

Созданы:

- `requirements.txt`
- `.env.example`
- `docs/live_run_aiogram3.md`
- `tests/test_aiogram_config_assets.py`

Покрыто тестами:

- dependency declaration содержит `aiogram>=3,<4` и `python-dotenv>=1`;
- `.env.example` документирует token storage без реального token;
- real `.env` отсутствует в repository tree;
- runbook требует dry-run, single-chat gate, polling conflict check и BotFather token только после подтверждения.

Проверка: `49 passed`.

### done — подготовить handler для `🔴 attention_items`

Созданы:

- `src/tg_companion_bot/attention_items.py`
- `tests/test_attention_items.py`

Покрыто тестами:

- один `attention_item` рендерится как отдельное Telegram-ready сообщение;
- варианты решения превращаются в inline keyboard rows;
- callback data имеет namespace `attention:<attention_id>:<option_id>`;
- callback data проверяется по лимиту Telegram 64 bytes;
- выбранное решение возвращает payload без `reply_markup`, то есть кнопки пропадают;
- неизвестный вариант безопасно превращается в noop без кнопок.

Проверка: `53 passed`.

### done — интегрировать `attention_items` в dry-run CLI / adapter shell

Расширены:

- `src/tg_companion_bot/smoke_cli.py`
- `tests/test_smoke_cli.py`

Покрыто тестом:

- входной report JSON с массивом `attention_items` принимается CLI;
- каждый `🔴` item превращается в отдельный Telegram-ready payload;
- payload содержит `chat_id`, текст без сырого YAML и inline keyboard;
- callback data формируется как `attention:<attention_id>:<option_id>`;
- safety-флаги остаются `requires_token=False`, `consumes_updates=False`, `sends_messages=False`.

Проверка: `54 passed`.

### done — интегрировать callback выбора решения `attention:<id>:<option>` в dry-run CLI / adapter shell

Реализовано:

- принимать callback query namespace `attention`;
- находить исходный `attention_item` в state/report context;
- возвращать финальное Telegram-ready сообщение без `reply_markup`, чтобы кнопки пропадали;
- сохранять выбранное решение без повторного применения;
- оставлять безопасный отказ для неизвестных/устаревших/конфликтующих кнопок;
- не требовать BotFather token, polling и отправку сообщений.

Проверка: `90 passed`.

### done — подготовить Hermes gateway boundary

Созданы:

- `src/tg_companion_bot/hermes_gateway_adapter.py`;
- `tests/test_hermes_gateway_adapter.py`;
- `docs/hermes_gateway_integration.md`.

Boundary использует существующий Hermes `completion_feedback/task_final` контракт, подавляет кнопки у progress-сообщений, ограничивает chat/user и возвращает send/edit/callback plans без сети, token и polling.

### done — подготовить durable runtime state для Hermes boundary

Созданы:

- `src/tg_companion_bot/state_codec.py`;
- `src/tg_companion_bot/runtime_state_store.py`;
- `tests/test_runtime_state_store.py`;
- `docs/runtime_state_store.md`.

SQLite store хранится вне Vault/Git, использует schema version, WAL и `BEGIN IMMEDIATE`. Проверены restart round-trip, rollback, no-op revision, persisted message→accept, durable completion-feedback accept после restart без Obsidian write, real temp-Vault write, concurrent attention callback `applied + duplicate` и unauthorized no-op.

Проверка: `90 passed`.

### done — установить durable companion bridge в Hermes Gateway

После backup установлен opt-in bridge для существующих `fb:accept/revise/next`, добавлен local `.pth` import и включён service flag. Gateway перезапущен, Telegram polling восстановлен, real-Vault writes выключены.

Проверено:

- первый callback сохраняет decision и продолжает Hermes flow;
- duplicate после restart не dispatch-ится агенту повторно;
- конфликтующее действие отклоняется;
- ошибка bridge оставляет кнопку для retry;
- SQLite state находится вне Vault/Git;
- runbook и rollback: `docs/hermes_gateway_installation.md`.

### done — подготовить Telegram attention dispatcher

Созданы:

- `src/tg_companion_bot/attention_dispatcher.py`;
- `tests/test_attention_dispatcher.py`.

Покрыто тестами:

- dispatcher отправляет первый `🔴 attention_item` как отдельное Telegram-ready сообщение с inline-кнопками;
- callback выбранного варианта редактирует исходное сообщение без `reply_markup`, то есть кнопки исчезают;
- следующий `🔴` пункт отправляется только после выбора по предыдущему;
- stale/wrong callback безопасно редактируется без показа следующего пункта.

Проверка: `93 passed`.

### doing — подключить Telegram attention dispatcher к Hermes Gateway

Следующий шаг: связать `TelegramAttentionAction` с существующим Hermes Telegram adapter, чтобы реальные `🔴` пункты уходили отдельными сообщениями с кнопками и исчезали после выбора. После этого вернуться к live smoke `revise`/`next`.

### doing — завершить single-chat live smoke

Live `accept` пройден через restart-fallback path: SQLite revision `1`, один durable decision, pending state очищен, один synthetic Hermes dispatch, real Vault не изменён. Остались отдельные пользовательские проверки `revise` и `next`; Vault write остаётся выключенным.

### deferred — подготовить standalone `aiogram 3` adapter

Не выполнять до проверки интерфейса через существующий Hermes gateway. Standalone adapter нужен только как переносимый reference implementation.

### done — подготовить token-independent nightly Git checkpoint

Созданы скрипт, тесты и runbook. Dry-run проходит secret scan, компиляцию и полный pytest. Commit/push закрыты двойным gate: `--execute` плюс `NIGHTLY_GIT_ALLOW_WRITE=1`.

### done — зарегистрировать ночное git-обновление проекта

После подтверждения зарегистрирована отдельная Windows Task Scheduler задача `HermesCompanion Nightly Git Checkpoint`. Первый push выполнен в `origin/main`; Obsidian optimizer больше не отвечает за git этого проекта.

Проверка `2026-07-02`: последний запуск в `03:30` завершился с кодом `0`, пропусков нет, рабочее дерево чистое, `main` и `origin/main` совпадают на `efbca13`.

### todo — создать отдельный Telegram-бот через BotFather

Требует участия/подтверждения владельца продукта. Не выполнять автоматически.

## Не трогать без подтверждения

- credentials;
- `.env` с токенами;
- BotFather настройки;
- live polling;
- git commit;
- cron schedules;
- массовую перестройку Obsidian.
