from tg_companion_bot.rendering import Button, RenderedMessage
from tg_companion_bot.telegram_adapter_shell import (
    TelegramPayload,
    build_callback_data,
    rendered_message_to_telegram_payload,
)


def test_rendered_message_converts_to_framework_neutral_telegram_payload():
    rendered = RenderedMessage(
        text="🔎 приёмка\n\nИтог готов",
        status="🔎 приёмка",
        buttons=(
            Button(text="Принять результат", action="accept"),
            Button(text="Доработать результат", action="revise"),
        ),
    )

    payload = rendered_message_to_telegram_payload(rendered, result_id="task-123")

    assert isinstance(payload, TelegramPayload)
    assert payload.text == "🔎 приёмка\n\nИтог готов"
    assert payload.parse_mode is None
    assert payload.disable_web_page_preview is True
    assert payload.reply_markup == {
        "inline_keyboard": [
            [
                {"text": "Принять результат", "callback_data": "companion:accept:task-123"},
                {"text": "Доработать результат", "callback_data": "companion:revise:task-123"},
            ]
        ]
    }


def test_intermediate_message_has_no_reply_markup():
    rendered = RenderedMessage(
        text="▶️ выполняется\n\nРаботаю",
        status="▶️ выполняется",
        buttons=(),
    )

    payload = rendered_message_to_telegram_payload(rendered, result_id="task-456")

    assert payload.reply_markup is None


def test_callback_data_is_namespaced_and_rejects_unsafe_action():
    assert build_callback_data("accept", "task-1") == "companion:accept:task-1"

    try:
        build_callback_data("delete", "task-1")
    except ValueError as exc:
        assert "Unsupported callback action" in str(exc)
    else:
        raise AssertionError("unsafe action should be rejected")


def test_callback_data_rejects_too_long_payload():
    long_id = "x" * 80

    try:
        build_callback_data("accept", long_id)
    except ValueError as exc:
        assert "too long" in str(exc)
    else:
        raise AssertionError("Telegram callback data longer than 64 bytes should be rejected")
