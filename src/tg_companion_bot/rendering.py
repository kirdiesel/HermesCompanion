from __future__ import annotations

from dataclasses import dataclass, field

IN_PROGRESS_STATUS = "▶️ выполняется"
REVIEW_STATUS = "🔎 приёмка"
DONE_STATUS = "✅ готово"
ACCEPTED_STATUS = "информация"


@dataclass(frozen=True)
class Button:
    text: str
    action: str


@dataclass(frozen=True)
class RenderRequest:
    kind: str
    title: str
    done: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    next_step: str | None = None


@dataclass(frozen=True)
class RenderedMessage:
    text: str
    status: str
    buttons: list[Button]


def render_message(request: RenderRequest) -> RenderedMessage:
    status = _status_for_kind(request.kind)
    text = _render_text(request, status)
    buttons = _buttons_for_kind(request.kind)
    return RenderedMessage(text=text, status=status, buttons=buttons)


def _status_for_kind(kind: str) -> str:
    if kind == "final_result":
        return REVIEW_STATUS
    if kind == "progress":
        return IN_PROGRESS_STATUS
    if kind == "accepted":
        return DONE_STATUS
    return ACCEPTED_STATUS


def _buttons_for_kind(kind: str) -> list[Button]:
    if kind != "final_result":
        return []
    return [
        Button(text="Принять результат", action="accept"),
        Button(text="Доработать результат", action="revise"),
        Button(text="Показать следующий шаг", action="next"),
    ]


def _render_text(request: RenderRequest, status: str) -> str:
    lines = [f"## {request.title}", "", f"Статус: {status}"]

    if request.done:
        lines.extend(["", "Что сделано:"])
        lines.extend(f"- {item}" for item in request.done)

    if request.verified:
        lines.extend(["", "Что проверено:"])
        lines.extend(f"- {item}" for item in request.verified)

    if request.next_step:
        lines.extend(["", f"Следующий шаг: {request.next_step}"])

    return "\n".join(lines)
