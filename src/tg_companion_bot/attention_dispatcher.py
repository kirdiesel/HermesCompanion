from __future__ import annotations

from dataclasses import dataclass

from tg_companion_bot.attention_items import (
    AttentionItem,
    AttentionPayload,
    apply_attention_decision,
    attention_item_to_telegram_payload,
    parse_attention_callback_data,
)


@dataclass(frozen=True)
class TelegramAttentionAction:
    method: str
    chat_id: int | str
    text: str
    reply_markup: dict | None = None
    message_id: int | None = None


class AttentionDispatcher:
    """Framework-neutral dispatcher for sequential 🔴 attention decisions.

    The dispatcher does not send Telegram messages itself. It returns explicit
    send/edit actions so a Gateway adapter can attach real inline buttons,
    remove them after selection, and only then show the next attention item.
    """

    def __init__(self, *, chat_id: int | str, items: tuple[AttentionItem, ...]):
        self.chat_id = chat_id
        self._items = items
        self._index = 0
        self._started = False

    def start(self) -> TelegramAttentionAction:
        self._started = True
        if not self._items:
            return TelegramAttentionAction(
                method="send_message",
                chat_id=self.chat_id,
                text="✅ Нет пунктов, требующих внимания.",
                reply_markup=None,
            )
        return self._send_action(self._items[self._index])

    def handle_callback(self, *, callback_data: str, message_id: int) -> tuple[TelegramAttentionAction, ...]:
        if not self._started:
            self.start()

        callback = parse_attention_callback_data(callback_data)
        current = self._current_item()
        if callback is None or current is None or callback.attention_id != current.attention_id:
            return (
                TelegramAttentionAction(
                    method="edit_message_text",
                    chat_id=self.chat_id,
                    message_id=message_id,
                    text="⚠️ Неожиданный или устаревший вариант решения. Кнопки убраны; запроси актуальный пункт заново.",
                    reply_markup=None,
                ),
            )

        decision = apply_attention_decision(current, callback.option_id)
        edit_action = self._edit_action(decision.payload, message_id=message_id)

        if decision.applied:
            self._index += 1

        next_item = self._current_item()
        if decision.applied and next_item is not None:
            return (edit_action, self._send_action(next_item))
        return (edit_action,)

    def _current_item(self) -> AttentionItem | None:
        if self._index >= len(self._items):
            return None
        return self._items[self._index]

    def _send_action(self, item: AttentionItem) -> TelegramAttentionAction:
        payload = attention_item_to_telegram_payload(item)
        return TelegramAttentionAction(
            method="send_message",
            chat_id=self.chat_id,
            text=payload.text,
            reply_markup=payload.reply_markup,
        )

    def _edit_action(self, payload: AttentionPayload, *, message_id: int) -> TelegramAttentionAction:
        return TelegramAttentionAction(
            method="edit_message_text",
            chat_id=self.chat_id,
            message_id=message_id,
            text=payload.text,
            reply_markup=payload.reply_markup,
        )
