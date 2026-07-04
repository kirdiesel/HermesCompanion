from tg_companion_bot.attention_dispatcher import AttentionDispatcher
from tg_companion_bot.attention_items import AttentionItem, DecisionOption


def _item(attention_id: str, title: str) -> AttentionItem:
    return AttentionItem(
        attention_id=attention_id,
        title=title,
        project="Obsidian",
        path=f"C:/Vault/{attention_id}.md",
        reason="Требуется решение пользователя",
        risk="Можно выбрать неверное действие",
        recommended_option="keep",
        decision_options=(
            DecisionOption(id="exclude", label="Исключить", effect="Исключить из активного графа, файл не удалять"),
            DecisionOption(id="keep", label="Оставить как есть", effect="Ничего не менять"),
        ),
    )


def test_dispatcher_sends_first_attention_item_with_inline_buttons():
    dispatcher = AttentionDispatcher(chat_id=777, items=(_item("one", "Первый пункт"), _item("two", "Второй пункт")))

    outgoing = dispatcher.start()

    assert outgoing.method == "send_message"
    assert outgoing.chat_id == 777
    assert outgoing.text.startswith("🔴 Требует внимания: Первый пункт")
    assert outgoing.reply_markup == {
        "inline_keyboard": [
            [{"text": "Исключить", "callback_data": "attention:one:exclude"}],
            [{"text": "Оставить как есть", "callback_data": "attention:one:keep"}],
        ]
    }


def test_dispatcher_edits_selected_message_without_buttons_then_sends_next_item():
    dispatcher = AttentionDispatcher(chat_id=777, items=(_item("one", "Первый пункт"), _item("two", "Второй пункт")))
    dispatcher.start()

    actions = dispatcher.handle_callback(callback_data="attention:one:exclude", message_id=123)

    assert [action.method for action in actions] == ["edit_message_text", "send_message"]
    edit, next_send = actions
    assert edit.chat_id == 777
    assert edit.message_id == 123
    assert edit.reply_markup is None
    assert edit.text.startswith("✅ Решение принято: Исключить")
    assert next_send.text.startswith("🔴 Требует внимания: Второй пункт")
    assert next_send.reply_markup["inline_keyboard"][0][0]["callback_data"] == "attention:two:exclude"


def test_dispatcher_rejects_stale_or_wrong_callback_without_showing_next_item():
    dispatcher = AttentionDispatcher(chat_id=777, items=(_item("one", "Первый пункт"), _item("two", "Второй пункт")))
    dispatcher.start()

    actions = dispatcher.handle_callback(callback_data="attention:two:exclude", message_id=123)

    assert len(actions) == 1
    assert actions[0].method == "edit_message_text"
    assert actions[0].reply_markup is None
    assert "устаревший" in actions[0].text.lower() or "неожиданный" in actions[0].text.lower()
