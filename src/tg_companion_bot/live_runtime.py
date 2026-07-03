from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .attention_items import (
    AttentionDecisionRecord,
    AttentionItem,
    AttentionPayload,
    apply_attention_decision,
    decision_record_from_result,
    parse_attention_callback_data,
    recorded_decision_payload,
)
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


@dataclass(frozen=True)
class CompanionDecisionRecord:
    task_id: str
    action: str
    status: str
    follow_up: str


@dataclass
class RuntimeState:
    obsidian_root: Optional[Path] = None
    pending_results: Dict[str, PendingResult] = field(default_factory=dict)
    companion_decisions: Dict[str, CompanionDecisionRecord] = field(default_factory=dict)
    pending_attention_items: Dict[str, AttentionItem] = field(default_factory=dict)
    attention_decisions: Dict[str, AttentionDecisionRecord] = field(default_factory=dict)


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
    applied: bool = False
    duplicate: bool = False
    error: Optional[str] = None
    record: Optional[CompanionDecisionRecord] = None


@dataclass(frozen=True)
class RuntimeAttentionCallbackResult:
    ok: bool
    status: str
    error: Optional[str] = None
    applied: bool = False
    duplicate: bool = False
    record: Optional[AttentionDecisionRecord] = None
    payload: Optional[AttentionPayload] = None


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

    existing = state.companion_decisions.get(decision.task_id)
    if existing is not None:
        duplicate = existing.action == decision.action.value
        return RuntimeCallbackResult(
            action=decision.action,
            follow_up=existing.follow_up,
            duplicate=duplicate,
            error=None if duplicate else "companion_result_already_resolved",
            record=existing,
        )

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
                    accepted_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                    artifacts=[],
                    event_id=decision.task_id,
                ),
            )
        state.pending_results.pop(decision.task_id, None)
        record = CompanionDecisionRecord(
            task_id=decision.task_id,
            action=decision.action.value,
            status=callback_result.status or "",
            follow_up=recommendation or callback_result.user_message,
        )
        state.companion_decisions[decision.task_id] = record
        return RuntimeCallbackResult(
            action=decision.action,
            follow_up=recommendation or callback_result.user_message,
            persistence=persistence,
            applied=True,
            record=record,
        )

    if decision.action == CallbackAction.REVISE:
        text = pending.summary if pending is not None else "Нужна доработка."
        rendered = render_message(
            RenderRequest(kind="progress", title="Доработка", done=[text])
        )
        record = CompanionDecisionRecord(
            task_id=decision.task_id,
            action=decision.action.value,
            status=callback_result.status or "",
            follow_up=callback_result.user_message,
        )
        state.companion_decisions[decision.task_id] = record
        return RuntimeCallbackResult(
            action=decision.action,
            rendered=rendered,
            follow_up=callback_result.user_message,
            applied=True,
            record=record,
        )

    record = CompanionDecisionRecord(
        task_id=decision.task_id,
        action=decision.action.value,
        status=callback_result.status or "",
        follow_up=callback_result.user_message,
    )
    state.companion_decisions[decision.task_id] = record
    return RuntimeCallbackResult(
        action=decision.action,
        follow_up=callback_result.user_message,
        applied=True,
        record=record,
    )


def handle_runtime_attention_callback(
    callback_data: str,
    *,
    state: RuntimeState,
) -> RuntimeAttentionCallbackResult:
    decision = parse_attention_callback_data(callback_data)
    if decision is None:
        return RuntimeAttentionCallbackResult(ok=False, status="invalid", error="invalid_attention_callback")

    existing = state.attention_decisions.get(decision.attention_id)
    if existing is not None:
        duplicate = existing.option_id == decision.option_id
        return RuntimeAttentionCallbackResult(
            ok=duplicate,
            status="duplicate" if duplicate else "conflict",
            error=None if duplicate else "attention_already_resolved",
            duplicate=duplicate,
            record=existing,
            payload=recorded_decision_payload(existing, duplicate=duplicate),
        )

    item = state.pending_attention_items.get(decision.attention_id)
    if item is None:
        return RuntimeAttentionCallbackResult(ok=False, status="stale", error="stale_attention_callback")

    applied = apply_attention_decision(item, decision.option_id)
    if not applied.applied:
        return RuntimeAttentionCallbackResult(
            ok=False,
            status="unknown_option",
            error="unknown_attention_option",
            payload=applied.payload,
        )

    record = decision_record_from_result(item, applied)
    state.pending_attention_items.pop(item.attention_id, None)
    state.attention_decisions[item.attention_id] = record
    return RuntimeAttentionCallbackResult(
        ok=True,
        status="applied",
        applied=True,
        record=record,
        payload=applied.payload,
    )
