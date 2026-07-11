from __future__ import annotations

from dataclasses import dataclass, field

from .interaction_profile import DEFAULT_INTERACTION_PROFILE, InteractionProfile

IN_PROGRESS_STATUS = DEFAULT_INTERACTION_PROFILE.in_progress_status
REVIEW_STATUS = DEFAULT_INTERACTION_PROFILE.review_status
DONE_STATUS = DEFAULT_INTERACTION_PROFILE.done_status
ACCEPTED_STATUS = None


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
    actions: tuple[str, ...] | None = None


@dataclass(frozen=True)
class RenderedMessage:
    text: str
    status: str | None
    buttons: list[Button]


def render_message(
    request: RenderRequest,
    *,
    profile: InteractionProfile = DEFAULT_INTERACTION_PROFILE,
) -> RenderedMessage:
    status = _status_for_kind(request.kind, profile)
    text = _render_text(request, status)
    buttons = _buttons_for_kind(request, profile)
    return RenderedMessage(text=text, status=status, buttons=buttons)


def _status_for_kind(kind: str, profile: InteractionProfile) -> str | None:
    if kind == "final_result":
        return profile.review_status
    if kind == "progress":
        return profile.in_progress_status
    if kind == "accepted":
        return profile.done_status
    return None


def _buttons_for_kind(request: RenderRequest, profile: InteractionProfile) -> list[Button]:
    if request.kind != "final_result":
        return []
    actions = profile.review_actions if request.actions is None else request.actions
    return [Button(text=profile.label_for(action), action=action) for action in actions]


def _render_text(request: RenderRequest, status: str | None) -> str:
    lines = [request.title]
    if status:
        lines.extend(["", f"Статус: {status}"])

    if request.done:
        lines.extend(["", "Что сделано:"])
        lines.extend(f"- {item}" for item in request.done)

    if request.verified:
        lines.extend(["", "Что проверено:"])
        lines.extend(f"- {item}" for item in request.verified)

    if request.next_step:
        lines.extend(["", f"Следующий шаг: {request.next_step}"])

    return "\n".join(lines)
