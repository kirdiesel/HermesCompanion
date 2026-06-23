from tg_companion_bot.callbacks import CallbackAction
from tg_companion_bot.live_runtime import (
    IncomingMessage,
    RuntimeState,
    handle_incoming_message,
    handle_runtime_callback,
)


def test_handle_incoming_message_renders_review_without_sending():
    state = RuntimeState()

    result = handle_incoming_message(
        IncomingMessage(chat_id="chat-1", text="Сделай краткий итог", message_id="m1"),
        state=state,
    )

    assert result.should_send is False
    assert result.rendered.status == "🔎 приёмка"
    assert [button.text for button in result.rendered.buttons] == [
        "Принять результат",
        "Доработать результат",
        "Показать следующий шаг",
    ]
    assert state.pending_results["m1"].summary == "Сделай краткий итог"


def test_accept_callback_persists_when_obsidian_root_is_available(tmp_path):
    state = RuntimeState(obsidian_root=tmp_path)
    handle_incoming_message(
        IncomingMessage(chat_id="chat-1", text="Итог для Obsidian", message_id="m2"),
        state=state,
    )

    result = handle_runtime_callback(
        callback_data="companion:accept:m2",
        state=state,
        project="Проект",
        recommendation="Следующий шаг",
    )

    assert result.action == CallbackAction.ACCEPT
    assert result.persistence is not None
    assert result.persistence.project_note.exists()
    assert result.persistence.decision_log.exists()
    assert result.follow_up == "Следующий шаг"
    assert "m2" not in state.pending_results


def test_revise_callback_keeps_pending_result_for_draft_revision():
    state = RuntimeState()
    handle_incoming_message(
        IncomingMessage(chat_id="chat-1", text="Черновик", message_id="m3"),
        state=state,
    )

    result = handle_runtime_callback("companion:revise:m3", state=state)

    assert result.action == CallbackAction.REVISE
    assert result.rendered.status == "▶️ выполняется"
    assert "m3" in state.pending_results


def test_unknown_callback_is_safe_noop():
    state = RuntimeState()

    result = handle_runtime_callback("bad:data", state=state)

    assert result.action is None
    assert result.follow_up == "Ничего не изменено."
