from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .attention_items import AttentionItem, attention_item_to_telegram_payload
from .callbacks import handle_callback
from .live_runtime import (
    IncomingMessage,
    RuntimeCallbackResult,
    RuntimeState,
    handle_incoming_message,
    handle_runtime_attention_callback,
    handle_runtime_callback,
)
from .runtime_state_store import SQLiteRuntimeStateStore


@dataclass(frozen=True)
class HermesInboundEvent:
    kind: str
    chat_id: str
    user_id: str
    message_id: str
    text: str = ""
    callback_data: str = ""


@dataclass(frozen=True)
class HermesAction:
    kind: str
    chat_id: str
    text: str = ""
    message_id: Optional[str] = None
    callback_text: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    reply_markup: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class HermesActionPlan:
    ok: bool
    actions: tuple[HermesAction, ...] = ()
    error: Optional[str] = None
    requires_token: bool = False
    consumes_updates: bool = False
    sends_messages: bool = False


def _is_authorized(event: HermesInboundEvent, *, allowed_chat_id: str, allowed_user_id: Optional[str]) -> bool:
    if str(event.chat_id) != str(allowed_chat_id):
        return False
    return allowed_user_id is None or str(event.user_id) == str(allowed_user_id)


def _callback_actions(
    event: HermesInboundEvent,
    *,
    text: str,
    answer: str,
    metadata: dict[str, Any],
) -> tuple[HermesAction, ...]:
    return (
        HermesAction(
            kind="answer_callback",
            chat_id=event.chat_id,
            message_id=event.message_id,
            callback_text=answer,
            metadata={"callback_answer": True},
        ),
        HermesAction(
            kind="edit_message",
            chat_id=event.chat_id,
            message_id=event.message_id,
            text=text,
            metadata={"callback_answer": True, **metadata},
            reply_markup=None,
        ),
    )


def plan_hermes_event(
    event: HermesInboundEvent,
    *,
    state: RuntimeState,
    allowed_chat_id: str,
    allowed_user_id: Optional[str] = None,
) -> HermesActionPlan:
    if not _is_authorized(event, allowed_chat_id=allowed_chat_id, allowed_user_id=allowed_user_id):
        return HermesActionPlan(ok=False, error="unauthorized_source")

    if event.kind == "progress":
        if not event.text.strip():
            return HermesActionPlan(ok=False, error="empty_message")
        return HermesActionPlan(
            ok=True,
            actions=(
                HermesAction(
                    kind="send_message",
                    chat_id=event.chat_id,
                    text=event.text,
                    metadata={
                        "task_final": False,
                        "suppress_completion_feedback": True,
                        "status_key": "companion_progress",
                    },
                ),
            ),
        )

    if event.kind == "message":
        if not event.text.strip() or not event.message_id:
            return HermesActionPlan(ok=False, error="invalid_message")
        result = handle_incoming_message(
            IncomingMessage(
                chat_id=event.chat_id,
                text=event.text,
                message_id=event.message_id,
            ),
            state=state,
        )
        return HermesActionPlan(
            ok=True,
            actions=(
                HermesAction(
                    kind="send_message",
                    chat_id=event.chat_id,
                    text=result.rendered.text,
                    metadata={
                        "completion_feedback": True,
                        "task_final": True,
                        "suppress_completion_feedback": False,
                        "companion_result_id": event.message_id,
                    },
                ),
            ),
        )

    if event.kind != "callback" or not event.callback_data:
        return HermesActionPlan(ok=False, error="unsupported_event")

    if event.callback_data.startswith("attention:"):
        result = handle_runtime_attention_callback(event.callback_data, state=state)
        if result.payload is None:
            return HermesActionPlan(ok=False, error=result.error or "invalid_attention_callback")
        record = result.record
        answer = record.selected_label if record is not None else "Решение не применено"
        actions = _callback_actions(
            event,
            text=result.payload.text,
            answer=answer,
            metadata={
                "attention_callback": True,
                "attention_status": result.status,
                "attention_applied": result.applied,
            },
        )
        return HermesActionPlan(ok=result.ok, actions=actions, error=result.error)

    if event.callback_data.startswith("companion:"):
        callback = handle_callback(event.callback_data)
        if callback.task_id is None:
            return HermesActionPlan(ok=False, error="invalid_companion_callback")
        runtime = handle_runtime_callback(event.callback_data, state=state)
        text = runtime.rendered.text if runtime.rendered is not None else f"Статус: {callback.status}"
        if runtime.follow_up:
            text = f"{text}\n\n{runtime.follow_up}"
        actions = _callback_actions(
            event,
            text=text,
            answer=callback.status or "Принято",
            metadata={
                "companion_callback": True,
                "companion_action": runtime.action.value if runtime.action is not None else None,
                "companion_applied": runtime.applied,
                "companion_duplicate": runtime.duplicate,
                "companion_error": runtime.error,
            },
        )
        return HermesActionPlan(ok=runtime.error is None, actions=actions, error=runtime.error)

    return HermesActionPlan(ok=False, error="unsupported_callback")


def plan_attention_item(
    item: AttentionItem,
    *,
    chat_id: str,
    state: RuntimeState,
) -> HermesActionPlan:
    if item.attention_id in state.attention_decisions:
        return HermesActionPlan(ok=False, error="attention_already_resolved")
    state.pending_attention_items[item.attention_id] = item
    payload = attention_item_to_telegram_payload(item)
    return HermesActionPlan(
        ok=True,
        actions=(
            HermesAction(
                kind="send_attention",
                chat_id=chat_id,
                text=payload.text,
                metadata={"task_final": False, "suppress_completion_feedback": True},
                reply_markup=payload.reply_markup,
            ),
        ),
    )


def plan_persisted_hermes_event(
    event: HermesInboundEvent,
    *,
    store: SQLiteRuntimeStateStore,
    allowed_chat_id: str,
    allowed_user_id: Optional[str] = None,
    obsidian_root: Path | str | None = None,
) -> HermesActionPlan:
    """Plan one Hermes event and atomically persist any resulting state change."""

    with store.transaction(obsidian_root=obsidian_root) as state:
        return plan_hermes_event(
            event,
            state=state,
            allowed_chat_id=allowed_chat_id,
            allowed_user_id=allowed_user_id,
        )


def plan_persisted_attention_item(
    item: AttentionItem,
    *,
    chat_id: str,
    store: SQLiteRuntimeStateStore,
) -> HermesActionPlan:
    """Plan one attention item and persist it before the Gateway sends actions."""

    with store.transaction() as state:
        return plan_attention_item(item, chat_id=chat_id, state=state)


def apply_persisted_completion_feedback(
    *,
    action: str,
    chat_id: str,
    message_id: str,
    result_text: str,
    store: SQLiteRuntimeStateStore,
    project: str = "Inbox",
    recommendation: Optional[str] = None,
    obsidian_root: Path | str | None = None,
) -> RuntimeCallbackResult:
    """Map an existing Hermes `fb:*` button to durable companion state."""

    task_id = f"telegram-{chat_id}-{message_id}"
    callback_data = f"companion:{action}:{task_id}"
    with store.transaction(obsidian_root=obsidian_root) as state:
        if task_id not in state.pending_results and task_id not in state.companion_decisions:
            handle_incoming_message(
                IncomingMessage(
                    chat_id=str(chat_id),
                    message_id=task_id,
                    text=result_text,
                ),
                state=state,
            )
        return handle_runtime_callback(
            callback_data,
            state=state,
            project=project,
            recommendation=recommendation,
        )
