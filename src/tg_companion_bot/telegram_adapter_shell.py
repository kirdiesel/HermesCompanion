from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .rendering import RenderedMessage

_ALLOWED_CALLBACK_ACTIONS = {"accept", "revise", "next"}
_TELEGRAM_CALLBACK_DATA_LIMIT = 64


@dataclass(frozen=True)
class TelegramPayload:
    text: str
    parse_mode: Optional[str] = None
    disable_web_page_preview: bool = True
    reply_markup: Optional[Dict[str, Any]] = None


def build_callback_data(action: str, result_id: str) -> str:
    if action not in _ALLOWED_CALLBACK_ACTIONS:
        raise ValueError(f"Unsupported callback action: {action}")
    callback_data = f"companion:{action}:{result_id}"
    if len(callback_data.encode("utf-8")) > _TELEGRAM_CALLBACK_DATA_LIMIT:
        raise ValueError("Telegram callback data is too long")
    return callback_data


def rendered_message_to_telegram_payload(
    rendered: RenderedMessage,
    *,
    result_id: str,
) -> TelegramPayload:
    return TelegramPayload(
        text=rendered.text,
        parse_mode=None,
        disable_web_page_preview=True,
        reply_markup=_build_inline_keyboard(rendered, result_id),
    )


def _build_inline_keyboard(
    rendered: RenderedMessage,
    result_id: str,
) -> Optional[Dict[str, Tuple[Tuple[Dict[str, str], ...], ...]]]:
    if not rendered.buttons:
        return None

    row = [
        {"text": button.text, "callback_data": build_callback_data(button.action, result_id)}
        for button in rendered.buttons
    ]
    return {"inline_keyboard": [row]}
