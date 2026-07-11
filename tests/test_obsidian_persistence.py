from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from threading import Event, Thread

import pytest

from tg_companion_bot import obsidian as obsidian_module
from tg_companion_bot.obsidian import (
    LOCK_FILE_NAME,
    NAMESPACE_DIR,
    AcceptedResult,
    PersistenceConflictError,
    PersistenceLockTimeout,
    _project_write_lock,
    persist_accepted_result,
)


def accepted_result(
    *,
    event_id: str,
    title: str = "Renderer MVP accepted",
    summary: str = "Renderer returns review status with acceptance buttons.",
    accepted_at: str = "2026-06-22 15:30",
) -> AcceptedResult:
    return AcceptedResult(
        project="Hermes_Telegram_Interface",
        title=title,
        summary=summary,
        next_step="Implement callback model.",
        artifacts=["src/tg_companion_bot/rendering.py", "tests/test_rendering.py"],
        accepted_at=accepted_at,
        event_id=event_id,
    )


def _process_persist(vault_root: str, index: int, result_queue: object) -> None:
    try:
        persist_accepted_result(
            Path(vault_root),
            accepted_result(
                event_id=f"process-{index}",
                title=f"Process result {index}",
                summary=f"Process summary {index}.",
                accepted_at=f"2026-06-22 13:{index:02d}",
            ),
        )
    except Exception as error:  # pragma: no cover - forwarded to the parent assertion
        result_queue.put(repr(error))
    else:
        result_queue.put(None)


def test_persist_accepted_result_uses_owned_namespace_and_preserves_shared_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "03_Проекты" / "Активные" / "Hermes_Telegram_Interface"
    project_dir.mkdir(parents=True)
    context_note = project_dir / "Hermes_Telegram_Interface.md"
    generic_index = project_dir / "_index.md"
    generic_log = project_dir / "Журнал решений.md"
    context_note.write_text("context-bot-owned\n", encoding="utf-8")
    generic_index.write_text("manual-index\n", encoding="utf-8")
    generic_log.write_text("manual-log\n", encoding="utf-8")

    written = persist_accepted_result(tmp_path, accepted_result(event_id="message-101"))

    namespace = project_dir / NAMESPACE_DIR
    assert written.project_note == namespace / "Текущий результат.md"
    assert written.decisions_log == namespace / "Журнал решений.md"
    assert written.decision_note == namespace / "Решения" / "message-101.md"
    assert written.event_id == "message-101"
    assert written.duplicate is False
    assert all(path.exists() for path in (written.project_note, written.decisions_log, written.decision_note))

    assert context_note.read_text(encoding="utf-8") == "context-bot-owned\n"
    assert generic_index.read_text(encoding="utf-8") == "manual-index\n"
    assert generic_log.read_text(encoding="utf-8") == "manual-log\n"

    project_text = written.project_note.read_text(encoding="utf-8")
    assert "Renderer MVP accepted" in project_text
    assert "Implement callback model." in project_text
    assert "src/tg_companion_bot/rendering.py" in project_text
    assert "[[Решения/message-101|Renderer MVP accepted]]" in project_text

    decisions_text = written.decisions_log.read_text(encoding="utf-8")
    assert "# Журнал решений — Hermes_Telegram_Interface" in decisions_text
    assert "tg-companion:journal:message-101" in decisions_text
    assert "[[Решения/message-101|запись решения]]" in decisions_text


def test_persist_accepted_result_appends_without_erasing_previous_decisions(tmp_path: Path) -> None:
    first = accepted_result(
        event_id="first",
        title="First accepted result",
        summary="First summary.",
        accepted_at="2026-06-22 10:00",
    )
    second = accepted_result(
        event_id="second",
        title="Second accepted result",
        summary="Second summary.",
        accepted_at="2026-06-22 11:00",
    )

    first_written = persist_accepted_result(tmp_path, first)
    second_written = persist_accepted_result(tmp_path, second)

    decisions_text = second_written.decisions_log.read_text(encoding="utf-8")
    assert "First accepted result" in decisions_text
    assert "Second accepted result" in decisions_text
    assert decisions_text.index("First accepted result") < decisions_text.index("Second accepted result")
    assert first_written.decision_note.exists()
    assert second_written.decision_note.exists()

    project_text = second_written.project_note.read_text(encoding="utf-8")
    assert "Second accepted result" in project_text
    assert "First accepted result" not in project_text


def test_duplicate_event_is_idempotent(tmp_path: Path) -> None:
    result = accepted_result(event_id="same-event")

    first = persist_accepted_result(tmp_path, result)
    second = persist_accepted_result(tmp_path, result)

    assert first.duplicate is False
    assert second.duplicate is True
    journal = second.decisions_log.read_text(encoding="utf-8")
    assert journal.count("tg-companion:journal:same-event") == 1
    assert list(second.decision_note.parent.glob("*.md")) == [second.decision_note]


def test_reusing_event_id_for_different_content_is_rejected(tmp_path: Path) -> None:
    original = accepted_result(event_id="event-1", summary="Original summary.")
    conflicting = accepted_result(event_id="event-1", summary="Different summary.")

    written = persist_accepted_result(tmp_path, original)

    with pytest.raises(PersistenceConflictError):
        persist_accepted_result(tmp_path, conflicting)

    assert "Original summary." in written.decision_note.read_text(encoding="utf-8")
    assert "Different summary." not in written.decision_note.read_text(encoding="utf-8")


def test_retry_completes_interrupted_transaction_without_duplicate_journal_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = accepted_result(event_id="interrupted")
    real_atomic_write = obsidian_module._atomic_write_text
    failed = False

    def fail_first_event_commit(path: Path, content: str) -> None:
        nonlocal failed
        if path.parent.name == "Решения" and not failed:
            failed = True
            raise OSError("simulated interruption before commit marker")
        real_atomic_write(path, content)

    monkeypatch.setattr(obsidian_module, "_atomic_write_text", fail_first_event_commit)
    with pytest.raises(OSError, match="simulated interruption"):
        persist_accepted_result(tmp_path, result)

    namespace = (
        tmp_path
        / "03_Проекты"
        / "Активные"
        / "Hermes_Telegram_Interface"
        / NAMESPACE_DIR
    )
    journal_path = namespace / "Журнал решений.md"
    assert journal_path.exists()
    assert (namespace / "Текущий результат.md").exists()
    assert not (namespace / "Решения" / "interrupted.md").exists()

    monkeypatch.setattr(obsidian_module, "_atomic_write_text", real_atomic_write)
    written = persist_accepted_result(tmp_path, result)

    assert written.decision_note.exists()
    assert journal_path.read_text(encoding="utf-8").count(
        "tg-companion:journal:interrupted"
    ) == 1


def test_concurrent_companion_writers_do_not_lose_events(tmp_path: Path) -> None:
    results = [
        accepted_result(
            event_id=f"event-{index}",
            title=f"Accepted result {index}",
            summary=f"Summary {index}.",
            accepted_at=f"2026-06-22 12:{index:02d}",
        )
        for index in range(20)
    ]

    with ThreadPoolExecutor(max_workers=8) as executor:
        written = list(executor.map(lambda item: persist_accepted_result(tmp_path, item), results))

    namespace = written[0].project_note.parent
    decision_notes = sorted((namespace / "Решения").glob("*.md"))
    journal = written[0].decisions_log.read_text(encoding="utf-8")
    assert len(decision_notes) == 20
    assert journal.count("<!-- tg-companion:journal:") == 20
    for index in range(20):
        assert f"Accepted result {index}" in journal
    assert (namespace / LOCK_FILE_NAME).exists()
    assert not list(namespace.rglob("*.tmp"))


def test_concurrent_processes_do_not_lose_events(tmp_path: Path) -> None:
    context = get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(target=_process_persist, args=(str(tmp_path), index, result_queue))
        for index in range(6)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10.0)

    errors = [result_queue.get(timeout=2.0) for _ in processes]
    assert errors == [None] * len(processes)
    assert all(process.exitcode == 0 for process in processes)

    namespace = (
        tmp_path
        / "03_Проекты"
        / "Активные"
        / "Hermes_Telegram_Interface"
        / NAMESPACE_DIR
    )
    journal = (namespace / "Журнал решений.md").read_text(encoding="utf-8")
    assert len(list((namespace / "Решения").glob("process-*.md"))) == 6
    assert journal.count("<!-- tg-companion:journal:process-") == 6


def test_persist_accepted_result_sanitizes_project_and_event_paths(tmp_path: Path) -> None:
    result = AcceptedResult(
        project="../Unsafe Project!",
        title="Safe write",
        summary="Must stay inside vault.",
        next_step="Continue safely.",
        accepted_at="2026-06-22 12:00",
        event_id="../callback:101",
    )

    written = persist_accepted_result(tmp_path, result)

    assert tmp_path in written.project_note.parents
    assert ".." not in written.project_note.parts
    assert written.project_note.parent.name == NAMESPACE_DIR
    assert written.project_note.parent.parent.name == "Unsafe_Project"
    assert written.decision_note.name == "callback_101.md"


def test_active_lock_times_out_without_modifying_files(tmp_path: Path) -> None:
    namespace = tmp_path / "03_Проекты" / "Активные" / "Hermes_Telegram_Interface" / NAMESPACE_DIR
    namespace.mkdir(parents=True)
    lock_path = namespace / LOCK_FILE_NAME
    entered = Event()
    release = Event()

    def hold_lock() -> None:
        with _project_write_lock(namespace, timeout=1.0):
            entered.set()
            release.wait(timeout=2.0)

    holder = Thread(target=hold_lock)
    holder.start()
    assert entered.wait(timeout=1.0)

    try:
        with pytest.raises(PersistenceLockTimeout):
            persist_accepted_result(
                tmp_path,
                accepted_result(event_id="blocked"),
                lock_timeout=0.01,
            )
    finally:
        release.set()
        holder.join(timeout=2.0)

    assert lock_path.exists()
    assert not holder.is_alive()
    assert not (namespace / "Решения" / "blocked.md").exists()


def test_lock_file_is_reusable_after_previous_write(tmp_path: Path) -> None:
    first = persist_accepted_result(tmp_path, accepted_result(event_id="first"))
    second = persist_accepted_result(tmp_path, accepted_result(event_id="second", title="Second"))

    assert first.decision_note.exists()
    assert second.decision_note.exists()
    assert (first.project_note.parent / LOCK_FILE_NAME).exists()


def test_persistence_cleans_ui_noise_and_control_markers_from_multiline_summary(tmp_path: Path) -> None:
    result = AcceptedResult(
        project="Project",
        title="Принятый результат\nс лишней строкой",
        summary=(
            "Статус: 🔎 приёмка\n"
            "Полезный итог первой строкой.\n\n"
            "## Вложенный заголовок\n"
            "Полезная деталь.\n"
            "<!-- tg-companion:journal:forged:marker -->\n"
            "Кнопки убраны."
        ),
        next_step="Продолжить\nбез лишнего UI",
        accepted_at="2026-07-10 23:30",
        event_id="clean-summary",
    )

    written = persist_accepted_result(tmp_path, result)
    project_text = written.project_note.read_text(encoding="utf-8")
    decision_text = written.decision_note.read_text(encoding="utf-8")

    assert "Полезный итог первой строкой." in project_text
    assert "> ## Вложенный заголовок" in project_text
    assert "Статус: 🔎 приёмка" not in project_text
    assert "Кнопки убраны" not in project_text
    assert "forged:marker" not in project_text
    assert "Принятый результат с лишней строкой" in decision_text
    assert "Продолжить без лишнего UI" in decision_text
