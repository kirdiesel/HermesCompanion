# Vault multi-writer contract

`<vault-root>` is a shared Vault. A writer must own explicit files or a namespace; access to the same Vault root does not imply ownership of every note.

## Current ownership

### `tg-context-bot`

- `01_Ежедневные заметки\YYYY-MM-DD.md`: only the block between `tg-context` markers.
- `03_Проекты\Активные\<project>\<project>.md`: project structure created when missing.
- `03_Проекты\Активные\<project>\Telegram\` and `Контекст\`: context-bot project directories.

### `tg-companion-bot`

All accepted-result persistence is contained in:

```text
03_Проекты\Активные\<project>\_tg-companion\
|-- .write.lock
|-- Текущий результат.md
|-- Журнал решений.md
`-- Решения\
    `-- <event_id>.md
```

- `Решения\<event_id>.md` is an immutable source record.
- `event_id` is the idempotency key. Repeating the same event is a no-op; reusing the id for different content is an error.
- `Текущий результат.md` and `Журнал решений.md` are companion-owned views.
- `.write.lock` is a persistent hidden synchronization file. The OS lock, not file existence, indicates an active writer.
- Markdown updates use same-directory temporary files and atomic `os.replace`.
- The immutable event note is written last as the transaction commit marker. A retry after an earlier interruption completes missing views without duplicating the journal entry.

The companion must not modify generic project-root `_index.md`, project-root `Журнал решений.md`, context-bot project notes, or daily notes.

### Nightly optimizer and other writers

- May inspect `_tg-companion`.
- Must preserve event markers and immutable decision notes.
- Must not rename, merge, rewrite, or delete `_tg-companion` without an explicit migration and acceptance.
- Obvious cache/temp cleanup must ignore an active `.write.lock` and same-directory `*.tmp` files younger than the current write timeout.

## Failure behavior

- Lock wait beyond the configured timeout raises `PersistenceLockTimeout`; no accepted-result files are modified.
- An existing `event_id` with a different content hash raises `PersistenceConflictError`.
- A repeated event may repair a missing journal/current view but does not create a second decision entry.
- A process crash releases the OS file lock automatically. The hidden lock file remains reusable.

## Live activation gate

Before enabling real-Vault writes through Hermes Gateway:

1. Back up the target project directory.
2. Confirm the resolved project slug and `_tg-companion` target.
3. Use the Telegram result/message id as `event_id`.
4. Run one single-chat accepted-result smoke.
5. Verify that context-bot files and generic project-root notes are byte-for-byte unchanged.
6. Verify one immutable decision note, one journal entry, and the current-result view.
7. Repeat the callback and verify `duplicate=true` with no extra journal entry.

The persistence module does not activate real-Vault writes by itself. The separately approved Gateway installation keeps the real-Vault root unset until acceptance.
