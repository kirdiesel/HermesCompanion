from pathlib import Path

from tg_companion_bot.obsidian import AcceptedResult, persist_accepted_result


def test_persist_accepted_result_creates_project_note_and_decision_log(tmp_path: Path) -> None:
    result = AcceptedResult(
        project="Hermes_Telegram_Interface",
        title="Renderer MVP accepted",
        summary="Renderer returns review status with acceptance buttons.",
        next_step="Implement callback model.",
        artifacts=["src/tg_companion_bot/rendering.py", "tests/test_rendering.py"],
        accepted_at="2026-06-22 15:30",
    )

    written = persist_accepted_result(tmp_path, result)

    project_note = tmp_path / "03_Проекты" / "Активные" / "Hermes_Telegram_Interface" / "_index.md"
    decisions_log = tmp_path / "03_Проекты" / "Активные" / "Hermes_Telegram_Interface" / "Журнал решений.md"

    assert written.project_note == project_note
    assert written.decisions_log == decisions_log
    assert project_note.exists()
    assert decisions_log.exists()

    project_text = project_note.read_text(encoding="utf-8")
    assert "# Hermes_Telegram_Interface" in project_text
    assert "## Последний принятый результат" in project_text
    assert "Renderer MVP accepted" in project_text
    assert "Implement callback model." in project_text
    assert "src/tg_companion_bot/rendering.py" in project_text

    decisions_text = decisions_log.read_text(encoding="utf-8")
    assert "# Журнал решений — Hermes_Telegram_Interface" in decisions_text
    assert "2026-06-22 15:30" in decisions_text
    assert "Renderer MVP accepted" in decisions_text
    assert "Renderer returns review status with acceptance buttons." in decisions_text


def test_persist_accepted_result_appends_without_erasing_previous_decisions(tmp_path: Path) -> None:
    first = AcceptedResult(
        project="Project_A",
        title="First accepted result",
        summary="First summary.",
        next_step="Second task.",
        accepted_at="2026-06-22 10:00",
    )
    second = AcceptedResult(
        project="Project_A",
        title="Second accepted result",
        summary="Second summary.",
        next_step="Third task.",
        accepted_at="2026-06-22 11:00",
    )

    persist_accepted_result(tmp_path, first)
    persist_accepted_result(tmp_path, second)

    decisions_log = tmp_path / "03_Проекты" / "Активные" / "Project_A" / "Журнал решений.md"
    decisions_text = decisions_log.read_text(encoding="utf-8")

    assert "First accepted result" in decisions_text
    assert "Second accepted result" in decisions_text
    assert decisions_text.index("First accepted result") < decisions_text.index("Second accepted result")

    project_note = tmp_path / "03_Проекты" / "Активные" / "Project_A" / "_index.md"
    project_text = project_note.read_text(encoding="utf-8")
    assert "Second accepted result" in project_text
    assert "First accepted result" not in project_text


def test_persist_accepted_result_sanitizes_project_path(tmp_path: Path) -> None:
    result = AcceptedResult(
        project="../Unsafe Project!",
        title="Safe write",
        summary="Must stay inside vault.",
        next_step="Continue safely.",
        accepted_at="2026-06-22 12:00",
    )

    written = persist_accepted_result(tmp_path, result)

    assert tmp_path in written.project_note.parents
    assert ".." not in written.project_note.parts
    assert written.project_note.parent.name == "Unsafe_Project"
