# Текущий контекст проекта `tg-companion-bot`

Статус обновлён: `2026-07-02`.

Проект:

`<repository-root>`

Это отдельный Telegram-бот-компаньон, который должен стать **переносимым интерфейсным шаблоном** для будущих Telegram-ботов с агентами Hermes One.

Главная идея:

> Telegram-сообщение пользователя → агент выполняет задачу → выдаёт итог на приёмку → пользователь принимает/дорабатывает → результат пишется в Obsidian → предлагается следующий шаг.

Проект развивается осторожно: сначала reusable core и dry-run слои, потом только live Telegram запуск.

---

## Главная цель проекта

Создать Telegram-интерфейс взаимодействия с персональными агентами Hermes, который:

1. работает как удобный бот-компаньон;
2. не засоряет Telegram кнопками и техническим шумом;
3. поддерживает статусы задач;
4. фиксирует принятые результаты в Obsidian;
5. может быть переиспользован как стартовый UX для других агентов Hermes One;
6. безопасно отделяет core-логику от live Telegram polling, токенов и framework-зависимостей.

---

## Согласованная модель взаимодействия

### Базовый цикл

1. Пользователь пишет задачу в Telegram.
2. Бот/агент берёт задачу в работу.
3. Промежуточные сообщения идут **без кнопок**.
4. Итоговый результат попадает в статус:

`🔎 приёмка`

5. Под итогом появляются смысловые кнопки:
   - `Принять результат`
   - `Доработать результат`
   - `Показать следующий шаг`

6. Если пользователь принимает результат:
   - задача переходит в `✅ готово`;
   - очищенный итог записывается в Obsidian;
   - запускается рекомендация ассистента;
   - если рекомендации нет — выбирается следующий оптимальный шаг.

7. Если пользователь просит доработку:
   - задача возвращается в работу;
   - уточнение используется для следующей итерации.

---

## Статусы проекта

Используется только упрощённая модель:

- `▶️ выполняется` — задача в работе;
- `🔎 приёмка` — итог готов, ждёт решения пользователя;
- `✅ готово` — пользователь явно принял результат.

Важно:

> `✅ готово` нельзя ставить автоматически без подтверждения пользователя.

---

## Ключевые принципы интерфейса

### Кнопки

Кнопки нужны не под каждым сообщением, а только когда они реально управляют процессом.

Кнопки обязательны:

- под итоговым результатом;
- при приёмке;
- при неочевидном выборе следующего шага;
- перед внешними/публичными/рискованными действиями.

Кнопки не нужны:

- под промежуточными комментариями;
- под системными сообщениями;
- под простыми информационными ответами;
- под техническими статусами, если от пользователя не требуется действие.

### Переносимость

Интерфейс должен быть не одноразовой реализацией под один бот, а reusable core:

- renderer не зависит от Telegram framework;
- callbacks не зависят от Telegram framework;
- Obsidian persistence не зависит от Telegram token;
- live runtime не запускает polling;
- adapter shell готовит payload, но не отправляет сообщения сам;
- future agents могут использовать этот интерфейс как стартовый шаблон.

---

## Что уже сделано

### 1. Создан локальный проект

Папка:

`<repository-root>`

Создан локальный git-репозиторий.

Был сделан первый commit:

`410d262 Initialize tg companion bot MVP`

Потом был сделан commit:

`863d076 Add Obsidian persistence MVP`

Затем добавлены коммиты:

- `edb8c9b Add safe Telegram live adapter dry-run layer`
- `f56409e feat: complete companion interaction callbacks and Hermes gateway boundary`
- `7ade46e fix: retry unpushed nightly checkpoints`
- `efbca13 chore: nightly checkpoint 2026-06-30`

Текущий remote:

`https://github.com/kirdiesel/HermesCompanion.git`

После подтверждения зарегистрирована отдельная Windows Task Scheduler задача `HermesCompanion Nightly Git Checkpoint`, а `origin/main` синхронизирован с локальным `main`.

После этого действует правило:

> git commit/push днём не делать без отдельного подтверждения; штатное git-обновление проекта выполняет отдельный nightly Git checkpoint, а не Obsidian-аудит.

Последний синхронизированный git-снимок после проверки: `main` синхронизирован с `origin/main` на `efbca13`.

---

## Документы проекта

Созданы и обновляются:

### `PROJECT_CONTEXT.md`

Контекст проекта:

- зачем нужен бот;
- как он связан с Hermes;
- как он связан с Obsidian;
- какие статусы используются;
- что считается готовым результатом;
- какие действия требуют подтверждения.

### `HERMES_BRIEF.md`

Бриф для Hermes:

- роль проекта;
- цель MVP;
- сценарии;
- правила кнопок;
- правила приёмки;
- критерии готовности;
- ограничения безопасности.

### `AGENT_MANIFEST.md`

Манифест агента:

- миссия агента;
- зоны ответственности;
- что можно делать автономно;
- что требует подтверждения;
- требования к качеству;
- требование переносимости интерфейса.

### `BACKLOG.md`

Backlog проекта:

- закрытые задачи;
- текущие задачи;
- следующие шаги;
- ограничения по live запуску;
- правило про git update ночью.

### `README.md`

Техническое описание проекта:

- назначение;
- core-модули;
- текущий статус;
- как запускать тесты;
- что ещё не подключено;
- следующий технический шаг.

---

## Реализованные модули reusable core

### 1. `rendering.py`

Файл:

`src/tg_companion_bot/rendering.py`

Отвечает за:

- формирование итоговых сообщений;
- статусы:
  - `▶️ выполняется`
  - `🔎 приёмка`
  - `✅ готово`
- кнопки приёмки;
- отсутствие кнопок у промежуточных сообщений.

Покрыто тестами:

`tests/test_rendering.py`

---

### 2. `callbacks.py`

Файл:

`src/tg_companion_bot/callbacks.py`

Отвечает за callback model:

- `accept`
- `revise`
- `next`

Логика:

- `accept` переводит результат в `✅ готово`;
- если есть рекомендация — запускает рекомендацию;
- если рекомендации нет — выбирает следующий оптимальный шаг;
- `revise` возвращает задачу в работу;
- `next` показывает/готовит следующий шаг;
- неизвестный callback безопасно превращается в noop.

Покрыто тестами:

`tests/test_callbacks.py`

---

### 3. `obsidian.py`

Файл:

`src/tg_companion_bot/obsidian.py`

Отвечает за запись принятого результата в Obsidian с учётом параллельных writers.

Пишет только в собственный namespace:

- `_tg-companion/Текущий результат.md`;
- `_tg-companion/Журнал решений.md`;
- immutable `_tg-companion/Решения/<event_id>.md`.

Не изменяет daily notes, context-bot `<project>.md`, generic `_index.md` и root `Журнал решений.md`. Запись использует idempotency key, OS file lock и atomic replace.

Принцип:

> в Obsidian пишется очищенный итог, а не сырая переписка.

Покрыто тестами:

`tests/test_obsidian_persistence.py`

---

### 4. `live_adapter.py`

Файл:

`src/tg_companion_bot/live_adapter.py`

Отвечает за безопасный dry-run план live-адаптера.

Что делает:

- читает config;
- проверяет наличие token;
- не раскрывает token;
- строит dry-run план;
- отмечает blockers;
- запрещает polling по умолчанию;
- запрещает отправку сообщений по умолчанию;
- фиксирует риски:
  - polling conflict;
  - accidental sends;
  - token leakage.

Покрыто тестами:

`tests/test_live_adapter.py`

---

### 5. `live_runtime.py`

Файл:

`src/tg_companion_bot/live_runtime.py`

Это glue-слой между core и будущим Telegram adapter.

Он связывает:

- входящее сообщение;
- renderer;
- callback model;
- Obsidian persistence.

Но при этом:

- не требует token;
- не запускает polling;
- не отправляет сообщения;
- не зависит от `aiogram` или `python-telegram-bot`.

Покрыто тестами:

`tests/test_live_runtime.py`

---

### 6. `telegram_adapter_shell.py`

Файл:

`src/tg_companion_bot/telegram_adapter_shell.py`

Отвечает за преобразование core-результата в Telegram-ready payload.

Делает:

- `RenderedMessage` → payload;
- кнопки → `inline_keyboard`;
- callback data:
  - `companion:accept:<id>`
  - `companion:revise:<id>`
  - `companion:next:<id>`

Ограничения:

- не импортирует Telegram framework;
- не требует token;
- не запускает polling;
- проверяет лимит callback data.

Покрыто тестами:

`tests/test_telegram_adapter_shell.py`

---

### 7. `telegram_framework_adapter.py`

Файл:

`src/tg_companion_bot/telegram_framework_adapter.py`

Это concrete adapter mapping без live framework.

Он делает:

- Telegram-like dict update → `IncomingMessage`;
- callback query update → callback object;
- runtime result → Telegram payload.

Но всё ещё безопасен:

- не импортирует `aiogram`;
- не импортирует `python-telegram-bot`;
- не требует BotFather token;
- не запускает polling;
- не consuming updates;
- не отправляет сообщения.

Покрыто тестами:

`tests/test_telegram_framework_adapter.py`

---

### 8. `smoke_cli.py`

Файл:

`src/tg_companion_bot/smoke_cli.py`

Отвечает за полный dry-run цикл из командной строки:

- Telegram-like message update → runtime → Telegram payload JSON;
- Windows-safe stdout JSON через `ensure_ascii=True`;
- callback query update `companion:accept/revise/next:<id>`;
- `--state <path>` для сохранения минимального pending result между запусками;
- `--obsidian-root <path>` для записи принятого результата только в test vault;
- понятная ошибка `invalid_state` для повреждённого state file;
- safety-флаги `requires_token=False`, `consumes_updates=False`, `sends_messages=False` во всех ветках output.

Важно:

- CLI не требует BotFather token;
- не запускает polling;
- не consuming updates;
- не отправляет реальные Telegram-сообщения;
- запись в настоящий `<vault-root>` из smoke CLI заблокирована без отдельного подтверждения.

Покрыто тестами:

`tests/test_smoke_cli.py`

---

### 9. `state_codec.py` и `runtime_state_store.py`

Файлы:

- `src/tg_companion_bot/state_codec.py`;
- `src/tg_companion_bot/runtime_state_store.py`.

Готовят restart-safe state для live Hermes bridge:

- единый schema-versioned codec для pending results и attention state;
- SQLite вне Vault/Git;
- WAL и `BEGIN IMMEDIATE` для конкурентных callbacks;
- rollback при ошибке;
- commit только при реальном изменении state;
- persisted wrappers для Hermes events и attention items.

Покрыто тестами:

`tests/test_runtime_state_store.py`

---

## Текущий test status

Последний зафиксированный результат:

```text
90 passed
```

То есть на текущем этапе все тесты проекта проходили.

---

## Что уже достигнуто концептуально

Проект уже прошёл путь от пустой папки до проверяемого reusable интерфейсного ядра.

Сейчас есть:

- локальный git repo;
- проектная документация;
- renderer сообщений;
- модель callback-ов;
- запись принятого результата в Obsidian;
- multi-writer-safe ownership namespace для совместной работы с `tg-context-bot` и другими Vault writers;
- dry-run live adapter;
- runtime glue;
- Telegram payload shell;
- framework-neutral adapter mapping;
- full smoke CLI pipeline message → payload → callback accept/revise/next → state → temp Obsidian persistence;
- idempotent attention decision callbacks with persisted state;
- deterministic nightly Git checkpoint dry-run without LLM;
- no-network Hermes gateway action-plan boundary using the existing completion feedback contract;
- transactional SQLite runtime state boundary with restart recovery and concurrent callback serialization;
- installed opt-in Hermes Telegram companion bridge with durable `fb:*` callback idempotency and accepted restart smoke without Obsidian write;
- framework-кандидат `aiogram 3`;
- безопасный live-run plan и install/config dry-run без реального token.
- тестовое покрытие всех этих слоёв.

То есть уже создана основа, которую можно использовать не только для бота-компаньона, но и как стартовый интерфейс для других Hermes One Telegram-агентов.

---

## Что пока НЕ сделано

Пока не сделано специально:

- не подключён BotFather token;
- не создан `.env` с реальным token;
- не запущен live polling;
- live Telegram framework-кандидат выбран (`aiogram 3`), но live adapter skeleton ещё не подключён к реальному polling;
- не отправляются реальные Telegram-сообщения;
- не consuming updates;
- не настроен отдельный production service;
- GitHub remote настроен, первый push выполнен через подтверждённый nightly checkpoint flow;
- не подключена реальная авторизация к Telegram API отдельного бота.

Это осознанное ограничение: проект пока развивается в безопасном dry-run/TDD режиме.

---

## Git-снимок

После отделения nightly Git checkpoint от Obsidian-аудита изменения проекта больше не ждут LLM-аудита Obsidian.

Последнее подтверждённое синхронизированное состояние:

- ветка: `main`;
- remote: `origin https://github.com/kirdiesel/HermesCompanion.git`;
- `origin/main` указывает на `efbca13`;
- рабочее дерево чистое перед текущим обновлением статуса;
- Windows scheduler задача `HermesCompanion Nightly Git Checkpoint` зарегистрирована и находится в состоянии `Ready`;
- последний запуск: `2026-07-02 03:30`, результат `0`, пропущенных запусков нет;
- следующий запуск: `2026-07-03 03:30`.

Ночной запуск `2026-06-30` закоммитил и отправил статусные markdown-правки. Запуски `2026-07-01` и `2026-07-02` подтвердили чистое дерево и не создавали лишних коммитов.

---

## Связь с Obsidian

Проектная карточка:

`<vault-root>/<project-note>.md`

Она обновлялась после каждого крупного шага.

В ней фиксируются:

- текущий статус;
- следующий шаг;
- реализованные артефакты;
- закрытые задачи;
- ограничения;
- связь с концепцией Hermes One.

---

## Связь с ночной оптимизацией

Создан и активен nightly optimizer:

`nightly-obsidian-structure-optimizer`

Его роль:

- ночью перетряхивать структуру Obsidian;
- оптимизировать vault под логичную 3D-графовую схему;
- спорные изменения выносить в `🔎 приёмка`.

Git проекта вынесен в отдельную deterministic задачу:

`HermesCompanion Nightly Git Checkpoint`

Её роль:

- проверять `tg-companion-bot` без LLM;
- запускать secret scan, `py_compile` и полный `pytest`;
- выполнять commit/push только при двойном write-gate;
- повторять push ранее созданного, но не отправленного commit даже при чистом working tree.

Правило:

> в дневных рабочих циклах код можно менять и тестировать, но commit/push и cron/scheduler changes делать только после отдельного подтверждения.

---

## Главные задачи проекта

### Ближайшая задача

Провести single-chat live smoke подключённого boundary через **существующий Hermes gateway** без второго polling consumer и без real-Vault write:

```text
Hermes final/progress event
→ companion runtime
→ send/edit/callback action plan
→ existing Hermes Telegram adapter
```

Текущее состояние:

- использовать уже реализованные Hermes completion buttons;
- не запускать второй polling consumer;
- durable bridge установлен и Gateway перезапущен;
- Telegram polling подключён;
- duplicate/conflicting callbacks защищены SQLite state;
- live `accept` smoke пройден через восстановление без in-memory state;
- real-Vault writes выключены до отдельной приёмки.

---

### Следующие задачи

1. **Завершить single-chat live smoke без Vault write**
   - `accept` уже проверен через restart-fallback path;
   - проверить отдельные результаты для `revise` и `next`;
   - подтвердить отсутствие повторного agent dispatch после duplicate callback;
   - проверить state после restart.

2. **Интеграция с настоящим Obsidian Vault**
   - проверить реальную запись принятого результата;
   - проверить журнал решений;
   - проверить отсутствие сырого шума.

3. **Live attention flow**
   - подключить последовательную выдачу `attention_items`;
   - проверить кнопки решения и исчезновение keyboard;
   - сохранить weekly reminder policy.

4. **Переиспользуемый template**
   - оформить core как стартовый интерфейс для других агентов Hermes One.

5. **Delivery outbox (после MVP)**
   - повторять Telegram action после post-commit API failure без повторного применения решения.

---

## Критерии MVP

MVP можно считать готовым, когда:

1. отдельный бот принимает Telegram-сообщение;
2. создаёт задачу/результат;
3. выдаёт итог в `🔎 приёмка`;
4. показывает кнопки только под итогом;
5. `Принять результат` переводит в `✅ готово`;
6. принятый итог пишется в Obsidian;
7. `Доработать результат` возвращает задачу в работу;
8. `Показать следующий шаг` предлагает/запускает следующий шаг;
9. промежуточные сообщения идут без кнопок;
10. core можно переиспользовать в другом агентском Telegram-боте.

---

## Короткий итог

Проект `tg-companion-bot` сейчас находится в состоянии:

> **reusable core, multi-writer-safe Obsidian persistence и durable SQLite state покрыты тестами; companion bridge установлен в работающий Hermes Gateway, live `accept` smoke пройден, а `revise`/`next` и real-Vault write ещё не выполнялись.**

Уже есть проверяемая цепочка:

```text
rendering
→ callbacks
→ Obsidian persistence
→ live runtime
→ Telegram payload shell
→ framework-neutral adapter mapping
→ smoke CLI full dry-run callback pipeline
→ Hermes gateway action-plan boundary
→ installed durable Hermes companion bridge
```

Следующий лучший шаг:

> завершить live smoke для `revise` и `next`, затем отдельной приёмкой проверить одну real-Vault запись.
