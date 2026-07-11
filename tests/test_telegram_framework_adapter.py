from tg_companion_bot.telegram_framework_adapter import (
    CallbackQueryUpdate,
    MessageUpdate,
    adapt_callback_query_update,
    adapt_message_update,
    build_send_payload,
)
from tg_companion_bot.live_runtime import RuntimeState


def test_adapt_message_update_maps_minimal_telegram_dict_to_runtime_message():
    update = {
        "message": {
            "message_id": 42,
            "chat": {"id": 1001},
            "text": "Сделай итог по проекту",
        }
    }

    message = adapt_message_update(update)

    assert isinstance(message, MessageUpdate)
    assert message.runtime_message.chat_id == "1001"
    assert message.runtime_message.message_id == "42"
    assert message.runtime_message.text == "Сделай итог по проекту"


def test_adapt_message_update_rejects_non_text_or_missing_message():
    assert adapt_message_update({"edited_message": {}}) is None
    assert adapt_message_update({"message": {"message_id": 1, "chat": {"id": 2}}}) is None


def test_build_send_payload_runs_runtime_without_consuming_updates():
    state = RuntimeState()
    update = {
        "message": {
            "message_id": 77,
            "chat": {"id": 555},
            "text": "Готовый результат",
        }
    }

    send_payload = build_send_payload(update, state=state)

    assert send_payload is not None
    assert send_payload.chat_id == "555"
    assert "🔎 приёмка" in send_payload.payload.text
    assert send_payload.payload.reply_markup is not None
    assert send_payload.consumes_updates is False
    assert send_payload.sends_immediately is False
    assert "77" in state.pending_results


def test_adapt_callback_query_update_maps_callback_without_framework_dependency():
    update = {
        "callback_query": {
            "id": "abc",
            "data": "companion:accept:77",
            "message": {"message_id": 88, "chat": {"id": 555}},
        }
    }

    callback = adapt_callback_query_update(update)

    assert isinstance(callback, CallbackQueryUpdate)
    assert callback.callback_query_id == "abc"
    assert callback.chat_id == "555"
    assert callback.message_id == "88"
    assert callback.callback_data == "companion:accept:77"


def test_adapt_callback_query_update_rejects_unknown_prefix():
    assert adapt_callback_query_update({"callback_query": {"id": "abc", "data": "other:accept:1"}}) is None


def test_adapt_callback_query_update_accepts_attention_namespace():
    update = {
        "callback_query": {
            "id": "attention-cb",
            "data": "attention:review-1:keep",
            "message": {"message_id": 90, "chat": {"id": 555}},
        }
    }

    callback = adapt_callback_query_update(update)

    assert callback is not None
    assert callback.callback_data == "attention:review-1:keep"


def test_adapt_callback_query_update_rejects_callback_without_message_identity():
    update = {
        "callback_query": {
            "id": "abc",
            "data": "companion:accept:77",
            "message": {"chat": {"id": 555}},
        }
    }

    assert adapt_callback_query_update(update) is None
