from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from .callbacks import CallbackAction, CallbackResult, handle_callback, parse_callback_data
from .obsidian import AcceptedResult, PersistenceResult, persist_accepted_result
from .rendering import RenderRequest, RenderedMessage, render_message


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: str
    text: str
    message_id: str


@dataclass
class PendingResult:
    chat_id: str
    message_id: str
    summary: str


@dataclass
class RuntimeState:
    obsidian_root: Optional[Path] = None
    pending_results: Dict[str, PendingResult] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeMessageResult:
    rendered: RenderedMessage
    should_send: bool


@dataclass(frozen=True)
class RuntimeCallbackResult:
    action: Optional[CallbackAction]
    rendered: Optional[RenderedMessage] = None
    follow_up: str = ""
    persistence: Optional[PersistenceResult] = None


def handle_incoming_message(message: IncomingMessage, *, state: RuntimeState) -> RuntimeMessageResult:
    """Prepare a review message from an incoming Telegram message without sending it.

    This is framework-neutral runtime glue: adapters may convert the rendered result
    to aiogram/python-telegram-bot/etc. messages, but this function never consumes
    updates, sends messages, or touches credentials.
    """

    rendered = render_message(
        RenderRequest(
            kind="final_result",
            title="Итог задачи",
            done=[message.text],
        )
    )
    state.pending_results[message.message_id] = PendingResult(
        chat_id=message.chat_id,
        message_id=message.message_id,
        summary=message.text,
    )
    return RuntimeMessageResult(rendered=rendered, should_send=False)


def handle_runtime_callback(
    callback_data: str,
    *,
    state: RuntimeState,
    project: str = "Inbox",
    recommendation: Optional[str] = None,
) -> RuntimeCallbackResult:
    decision = parse_callback_data(callback_data)
    if decision is None:
        return RuntimeCallbackResult(action=None, follow_up="Ничего не изменено.")

    pending = state.pending_results.get(decision.task_id)
    callback_result: CallbackResult = handle_callback(
        callback_data,
        has_recommendation=bool(recommendation),
    )

    if decision.action == CallbackAction.ACCEPT:
        persistence = None
        if pending is not None and state.obsidian_root is not None:
            persistence = persist_accepted_result(
                state.obsidian_root,
                AcceptedResult(
                    project=project,
                    title="Принятый результат",
                    summary=pending.summary,
                    next_step=recommendation or callback_result.user_message,
                    accepted_at="runtime",
                    artifacts=[],
                ),
            )
        state.pending_results.pop(decision.task_id, None)
        return RuntimeCallbackResult(
            action=decision.action,
            follow_up=recommendation or callback_result.user_message,
            persistence=persistence,
        )

    if decision.action == CallbackAction.REVISE:
        text = pending.summary if pending is not None else "Нужна доработка."
        rendered = render_message(
            RenderRequest(kind="progress", title="Доработка", done=[text])
        )
        return RuntimeCallbackResult(
            action=decision.action,
            rendered=rendered,
            follow_up=callback_result.user_message,
        )

    return RuntimeCallbackResult(
        action=decision.action,
        follow_up=callback_result.user_message,
    )
