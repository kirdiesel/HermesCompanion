from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .live_runtime import IncomingMessage, RuntimeState, handle_incoming_message
from .telegram_adapter_shell import TelegramPayload, rendered_message_to_telegram_payload


@dataclass(frozen=True)
class MessageUpdate:
    runtime_message: IncomingMessage


@dataclass(frozen=True)
class CallbackQueryUpdate:
    callback_query_id: str
    chat_id: str
    message_id: str
    callback_data: str


@dataclass(frozen=True)
class PreparedSendPayload:
    chat_id: str
    payload: TelegramPayload
    consumes_updates: bool = False
    sends_immediately: bool = False


def adapt_message_update(update: Dict[str, Any]) -> Optional[MessageUpdate]:
    message = update.get("message")
    if not isinstance(message, dict):
        return None

    text = message.get("text")
    chat = message.get("chat")
    message_id = message.get("message_id")
    if not isinstance(text, str) or not isinstance(chat, dict) or message_id is None:
        return None

    chat_id = chat.get("id")
    if chat_id is None:
        return None

    return MessageUpdate(
        runtime_message=IncomingMessage(
            chat_id=str(chat_id),
            text=text,
            message_id=str(message_id),
        )
    )


def adapt_callback_query_update(update: Dict[str, Any]) -> Optional[CallbackQueryUpdate]:
    callback_query = update.get("callback_query")
    if not isinstance(callback_query, dict):
        return None

    data = callback_query.get("data")
    callback_query_id = callback_query.get("id")
    if (
        not isinstance(data, str)
        or not data.startswith(("companion:", "attention:"))
        or not callback_query_id
    ):
        return None

    message = callback_query.get("message") or {}
    chat = message.get("chat") if isinstance(message, dict) else {}
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    message_id = message.get("message_id") if isinstance(message, dict) else None
    if chat_id is None or message_id is None:
        return None

    return CallbackQueryUpdate(
        callback_query_id=str(callback_query_id),
        chat_id=str(chat_id),
        message_id=str(message_id),
        callback_data=data,
    )


def build_send_payload(
    update: Dict[str, Any],
    *,
    state: RuntimeState,
) -> Optional[PreparedSendPayload]:
    adapted = adapt_message_update(update)
    if adapted is None:
        return None

    runtime_result = handle_incoming_message(adapted.runtime_message, state=state)
    telegram_payload = rendered_message_to_telegram_payload(
        runtime_result.rendered,
        result_id=adapted.runtime_message.message_id,
    )
    return PreparedSendPayload(
        chat_id=adapted.runtime_message.chat_id,
        payload=telegram_payload,
        consumes_updates=False,
        sends_immediately=False,
    )
