# Статус `tg-companion-bot`

Дата аудита: `2026-07-10`.

## Итог

Проект имеет качественное тестируемое интерфейсное ядро и действующий durable bridge внутри Hermes Telegram Gateway. Это ещё не отдельный standalone Telegram-бот и не полностью замкнутый управленческий контур.

На момент аудита Hermes Gateway запущен, bridge активен, real-Vault writes выключены. Репозиторий до текущих правок был чистым и синхронизирован с `origin/main` на `b888b83`.

## Фактическая архитектура

```text
Telegram пользователя
  -> существующий Hermes Gateway polling
  -> Hermes agent result
  -> final-only fb:accept/revise/next buttons
  -> tg-companion durable bridge
  -> SQLite decision state
  -> synthetic Hermes turn
  -> optional accepted-result persistence (real Vault сейчас выключен)
```

Ночная оптимизация является соседней системой:

```text
03:00 local Obsidian audit
  -> Markdown report + attention_items JSON
03:30 optional AI semantic review
  -> semantic Markdown report
tg-companion
  -> должен доставить unresolved attention items в Telegram
```

## Сопоставление с требованиями

| Требование | Состояние |
|---|---|
| Обычное сообщение запускает Hermes-задачу | Работает через существующий Hermes Gateway |
| Кнопки только под итоговым ответом | Работает live |
| Минимально достаточное число кнопок | Core поддерживает; установленный Gateway пока показывает фиксированные 3 |
| `accept` продолжает работу и дедуплицируется | Работает; live smoke пройден |
| `revise` и `next` | Unit/integration зелёные; отдельный live smoke не выполнен |
| Явная приёмка перед `✅ готово` | Реализовано |
| Запись очищенного принятого результата в Obsidian | Temp Vault проверен; real Vault выключен |
| Запись в правильный проект | Не готово: нужен явный project routing |
| Безопасная совместная запись с `tg-context-bot` | Реализована через отдельный `_tg-companion` namespace |
| Ночные спорные пункты с кнопками | Adapter готов; live delivery не подключён |
| Недельное подавление повторных noncritical-вопросов | Реализовано в weekly attention IDs |
| Перенос способа общения одним prompt | Реализовано в `interaction_profile.py` и `docs/hermes_one_interface_prompt.md` |
| Ежемесячный ChatGPT export | Raw import существует; регулярный intake не автоматизирован |
| Минимум «воды» | Core уплотнён; качество самих Hermes-ответов ещё не измеряется |
| Ночной Git commit/push | Windows task работает, последний результат 0 |

## Исправлено этим аудитом

- Config теперь читает реальные prefixed keys из `.env.example`; legacy names сохранены как fallback.
- Callback без pending result возвращает `stale_companion_result`.
- Callback из другого чата возвращает `callback_chat_mismatch` до изменения state.
- Новые decision records хранят `chat_id`; старые schema-v1 records продолжают читаться.
- Consumed `revise/next` pending result очищается при появлении следующего результата в чате.
- `next` снимает старую keyboard.
- Info message не показывает статус вне согласованной тройки и не выводит literal Markdown heading.
- Renderer принимает configurable action subset и `InteractionProfile`.
- Handoff prompt не содержит локальных путей, имён, token или credentials.
- Attention text больше не дублирует все варианты и не объясняет пользователю, что кнопки удалены.
- Legacy nightly audit JSON преобразуется в canonical items; IDs стабильны в пределах ISO-недели.
- Smoke CLI блокирует не только корень реального Vault, но и любую его подпапку.
- JSON state smoke CLI записывается атомарно.

## Проверки

- Project suite, системный Python: `111 passed`.
- Project suite, Hermes venv: `111 passed`.
- Hermes Gateway completion-feedback suite: `8 passed`.
- `compileall`: проходит.
- Реальный `attention_items_2026-07-10.json`: dry-run успешно создал 2 Telegram payload без token/send.
- Hermes bridge log: активирован с `real Vault writes: False`.
- Runtime SQLite: schema 1, revision 2, 0 pending results, 2 accepted decisions до текущих правок.
- Windows task `HermesCompanion Nightly Git Checkpoint`: запуск 2026-07-10 03:30, result 0.

Backup перед правками:

```text
C:\AIProjects\Backups\tg-companion-bot-comprehensive-audit-20260710-232123
```

## Критические ограничения

- В реальном Vault одновременно существуют `Проекты` и канонический `03_Проекты`; companion пишет только в `03_Проекты`.
- `tg-context-bot` не является Git-репозиторием в проверенном пути и может параллельно изменяться другим агентом; его файлы в этом цикле не менялись.
- У `tg-context-bot` и companion нет общего cross-writer lock, поэтому они обязаны сохранять непересекающееся ownership файлов.
- Нет delivery outbox между SQLite commit и Telegram API.
- Standalone `aiogram` entrypoint отсутствует, `aiogram` в проверенных Python runtimes не установлен.
- Отдельный token не читался и не изменялся; текущий live interface использует token существующего Hermes Gateway.
- При выключенном ПК cron, Gateway и Windows task не выполняются.

## Оптимальный порядок продолжения

1. Подключить nightly attention adapter к Hermes Gateway без изменения cron-логики и провести один подтверждённый send/edit callback smoke.
2. Провести live smoke `revise` и `next` с real Vault выключенным.
3. Добавить явный project routing; только затем включить одну принятую запись в real Vault и проверить отсутствие изменений в файлах `tg-context-bot`.
4. Создать monthly ChatGPT import inbox + manifest; semantic extraction запускать после появления нового export, а не по пустому расписанию.
5. После двух недель использования оценить агрегаты interaction quality и только по фактам решать, нужен ли standalone bot или outbox.

Этот порядок критичен: включение real Vault до project routing создаст аккуратные, но неправильно классифицированные записи в `Inbox`; standalone polling сейчас добавит второй runtime без новой пользовательской ценности.
