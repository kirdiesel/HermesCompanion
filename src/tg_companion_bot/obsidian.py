from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AcceptedResult:
    project: str
    title: str
    summary: str
    next_step: str
    accepted_at: str
    artifacts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersistenceResult:
    project_note: Path
    decisions_log: Path


def persist_accepted_result(vault_root: Path | str, result: AcceptedResult) -> PersistenceResult:
    """Persist an accepted task result into an Obsidian project note and decision log.

    The MVP intentionally writes a clean summary, not a raw chat transcript:
    - project `_index.md` keeps the latest accepted result/current next step;
    - `Журнал решений.md` appends chronological accepted outcomes.
    """

    root = Path(vault_root).resolve()
    project_slug = _safe_project_slug(result.project)
    project_dir = root / "03_Проекты" / "Активные" / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)

    project_note = project_dir / "_index.md"
    decisions_log = project_dir / "Журнал решений.md"

    project_note.write_text(_render_project_note(project_slug, result), encoding="utf-8")

    if not decisions_log.exists():
        decisions_log.write_text(f"# Журнал решений — {project_slug}\n\n", encoding="utf-8")
    with decisions_log.open("a", encoding="utf-8") as handle:
        handle.write(_render_decision_entry(result))

    return PersistenceResult(project_note=project_note, decisions_log=decisions_log)


def _safe_project_slug(project: str) -> str:
    cleaned = project.strip().replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return cleaned or "Project"


def _render_project_note(project_slug: str, result: AcceptedResult) -> str:
    artifacts = _render_artifacts(result.artifacts)
    return (
        f"# {project_slug}\n\n"
        "## Последний принятый результат\n"
        f"- Дата принятия: {result.accepted_at}\n"
        f"- Результат: {result.title}\n"
        f"- Итог: {result.summary}\n"
        f"- Следующий шаг: {result.next_step}\n"
        f"{artifacts}\n"
        "## Связанные заметки\n"
        "- [[Журнал решений]]\n"
    )


def _render_decision_entry(result: AcceptedResult) -> str:
    artifacts = _render_artifacts(result.artifacts)
    return (
        f"## {result.accepted_at} — {result.title}\n"
        f"- Итог: {result.summary}\n"
        f"- Следующий шаг: {result.next_step}\n"
        f"{artifacts}\n"
    )


def _render_artifacts(artifacts: list[str]) -> str:
    if not artifacts:
        return "- Артефакты: нет\n"
    lines = ["- Артефакты:"]
    lines.extend(f"  - `{artifact}`" for artifact in artifacts)
    return "\n".join(lines) + "\n"
