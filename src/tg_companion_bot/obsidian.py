from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterator


NAMESPACE_DIR = "_tg-companion"
CURRENT_NOTE_NAME = "Текущий результат.md"
DECISIONS_LOG_NAME = "Журнал решений.md"
DECISIONS_DIR_NAME = "Решения"
LOCK_FILE_NAME = ".write.lock"
MAX_SUMMARY_CHARS = 8_000
_CONTROL_COMMENT = re.compile(
    r"<!--\s*(?:tg-companion|managed-by)\s*:.*?-->",
    flags=re.IGNORECASE | re.DOTALL,
)
_UI_NOISE_LINE = re.compile(
    r"^(?:Статус:\s*(?:▶️|🔎|✅)|Кнопки\s+(?:убраны|удалены)\.?$)",
    flags=re.IGNORECASE,
)


class PersistenceConflictError(RuntimeError):
    """Raised when an idempotency key is reused for different content."""


class PersistenceLockTimeout(RuntimeError):
    """Raised when another companion writer holds the project lock too long."""


@dataclass(frozen=True)
class AcceptedResult:
    project: str
    title: str
    summary: str
    next_step: str
    accepted_at: str
    artifacts: list[str] = field(default_factory=list)
    event_id: str | None = None


@dataclass(frozen=True)
class PersistenceResult:
    project_note: Path
    decisions_log: Path
    decision_note: Path
    event_id: str
    duplicate: bool = False

    @property
    def decision_log(self) -> Path:
        return self.decisions_log


def persist_accepted_result(
    vault_root: Path | str,
    result: AcceptedResult,
    *,
    lock_timeout: float = 5.0,
) -> PersistenceResult:
    """Persist one accepted result inside the companion-owned Vault namespace.

    The project root is shared with context bots, users, and optimizers. This
    writer therefore never modifies generic project files. Each accepted event
    gets an immutable note under `_tg-companion/Решения`, while companion-owned
    current/log views are updated under an exclusive lock with atomic replaces.
    """

    root = Path(vault_root).resolve()
    project_slug = _safe_project_slug(result.project)
    namespace_dir = root / "03_Проекты" / "Активные" / project_slug / NAMESPACE_DIR
    decisions_dir = namespace_dir / DECISIONS_DIR_NAME
    decisions_dir.mkdir(parents=True, exist_ok=True)

    event_id = _safe_event_id(result.event_id) if result.event_id else _derived_event_id(result)
    content_hash = _result_content_hash(result)
    event_marker = _event_marker(event_id, content_hash)

    project_note = namespace_dir / CURRENT_NOTE_NAME
    decisions_log = namespace_dir / DECISIONS_LOG_NAME
    decision_note = decisions_dir / f"{event_id}.md"

    with _project_write_lock(
        namespace_dir,
        timeout=lock_timeout,
    ):
        duplicate = decision_note.exists()
        if duplicate:
            existing = decision_note.read_text(encoding="utf-8")
            if event_marker not in existing:
                raise PersistenceConflictError(
                    f"Event id {event_id!r} already exists with different content."
                )

        journal = (
            decisions_log.read_text(encoding="utf-8")
            if decisions_log.exists()
            else f"# Журнал решений — {project_slug}\n\n"
        )
        journal_marker = _journal_marker(event_id, content_hash)
        if journal_marker not in journal:
            journal = _ensure_trailing_newline(journal) + _render_decision_entry(
                result,
                event_id,
                content_hash,
            )
            _atomic_write_text(decisions_log, journal)

        if not duplicate or not project_note.exists():
            _atomic_write_text(
                project_note,
                _render_project_note(project_slug, result, event_id),
            )

        if not duplicate:
            # The immutable event note is the transaction commit marker. If a
            # process stops earlier, retrying the same event repairs the views
            # and creates this note without duplicating the journal marker.
            _atomic_write_text(
                decision_note,
                _render_decision_note(result, event_id, content_hash),
            )

    return PersistenceResult(
        project_note=project_note,
        decisions_log=decisions_log,
        decision_note=decision_note,
        event_id=event_id,
        duplicate=duplicate,
    )


def _safe_project_slug(project: str) -> str:
    cleaned = project.strip().replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return cleaned or "Project"


def _safe_event_id(event_id: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "_", str(event_id).strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_-")
    if not cleaned:
        raise ValueError("event_id must contain at least one safe character")
    return cleaned[:64]


def _result_payload(result: AcceptedResult) -> dict[str, object]:
    return {
        "project": result.project,
        "title": result.title,
        "summary": result.summary,
        "next_step": result.next_step,
        "accepted_at": result.accepted_at,
        "artifacts": list(result.artifacts),
    }


def _result_content_hash(result: AcceptedResult) -> str:
    payload = json.dumps(
        _result_payload(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _derived_event_id(result: AcceptedResult) -> str:
    return f"result-{_result_content_hash(result)}"


def _event_marker(event_id: str, content_hash: str) -> str:
    return f"<!-- tg-companion:event:{event_id}:{content_hash} -->"


def _journal_marker(event_id: str, content_hash: str) -> str:
    return f"<!-- tg-companion:journal:{event_id}:{content_hash} -->"


def _render_project_note(project_slug: str, result: AcceptedResult, event_id: str) -> str:
    artifacts = _render_artifacts(result.artifacts)
    title = _clean_inline(result.title, max_chars=300)
    accepted_at = _clean_inline(result.accepted_at, max_chars=100)
    summary = _render_quote(_clean_summary(result.summary))
    next_step = _render_quote(_clean_inline(result.next_step, max_chars=2_000))
    return (
        "<!-- managed-by: tg-companion-bot -->\n"
        f"# Текущий результат — {project_slug}\n\n"
        f"- Дата принятия: {accepted_at}\n"
        f"- Результат: {title}\n\n"
        "## Итог\n"
        f"{summary}\n\n"
        "## Следующий шаг\n"
        f"{next_step}\n\n"
        f"{artifacts}"
        f"- Запись решения: [[{DECISIONS_DIR_NAME}/{event_id}|{title}]]\n\n"
        "## Связанные заметки\n"
        f"- [[{DECISIONS_LOG_NAME.removesuffix('.md')}]]\n"
    )


def _render_decision_note(
    result: AcceptedResult,
    event_id: str,
    content_hash: str,
) -> str:
    artifacts = _render_artifacts(result.artifacts)
    title = _clean_inline(result.title, max_chars=300)
    accepted_at = _clean_inline(result.accepted_at, max_chars=100)
    summary = _render_quote(_clean_summary(result.summary))
    next_step = _render_quote(_clean_inline(result.next_step, max_chars=2_000))
    return (
        f"{_event_marker(event_id, content_hash)}\n"
        "<!-- managed-by: tg-companion-bot; immutable: true -->\n"
        f"# {title}\n\n"
        f"- Дата принятия: {accepted_at}\n\n"
        "## Итог\n"
        f"{summary}\n\n"
        "## Следующий шаг\n"
        f"{next_step}\n\n"
        f"{artifacts}"
    )


def _render_decision_entry(
    result: AcceptedResult,
    event_id: str,
    content_hash: str,
) -> str:
    title = _clean_inline(result.title, max_chars=300)
    accepted_at = _clean_inline(result.accepted_at, max_chars=100)
    summary = _render_quote(_clean_summary(result.summary))
    next_step = _render_quote(_clean_inline(result.next_step, max_chars=2_000))
    return (
        f"{_journal_marker(event_id, content_hash)}\n"
        f"## {accepted_at} — {title}\n"
        "### Итог\n"
        f"{summary}\n\n"
        "### Следующий шаг\n"
        f"{next_step}\n\n"
        f"- Подробно: [[{DECISIONS_DIR_NAME}/{event_id}|запись решения]]\n\n"
    )


def _render_artifacts(artifacts: list[str]) -> str:
    if not artifacts:
        return "- Артефакты: нет\n"
    lines = ["- Артефакты:"]
    lines.extend(f"  - `{_clean_inline(artifact, max_chars=1_000)}`" for artifact in artifacts)
    return "\n".join(lines) + "\n"


def _clean_summary(value: str, *, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    text = str(value or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_COMMENT.sub("", text)
    lines: list[str] = []
    previous_blank = False
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if _UI_NOISE_LINE.match(line):
            continue
        if not line:
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line)
        previous_blank = False
    cleaned = "\n".join(lines).strip() or "Нет содержательного итога."
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def _clean_inline(value: str, *, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", _clean_summary(value, max_chars=max_chars)).strip()
    return cleaned[:max_chars].rstrip()


def _render_quote(value: str) -> str:
    return "\n".join(">" if not line else f"> {line}" for line in value.split("\n"))


def _ensure_trailing_newline(content: str) -> str:
    return content if content.endswith("\n") else content + "\n"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_ensure_trailing_newline(content))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


@contextmanager
def _project_write_lock(
    namespace_dir: Path,
    *,
    timeout: float,
) -> Iterator[None]:
    lock_path = namespace_dir / LOCK_FILE_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(timeout, 0.0)

    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())

        while True:
            try:
                _lock_handle(handle)
            except OSError:
                if time.monotonic() >= deadline:
                    raise PersistenceLockTimeout(f"Timed out waiting for {lock_path}")
                time.sleep(0.01)
                continue
            break

        try:
            yield
        finally:
            _unlock_handle(handle)


def _lock_handle(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
