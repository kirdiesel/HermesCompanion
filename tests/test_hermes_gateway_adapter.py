from pathlib import Path

from tg_companion_bot.attention_items import AttentionItem, DecisionOption
from tg_companion_bot.hermes_gateway_adapter import (
    HermesInboundEvent,
    plan_attention_item,
    plan_hermes_event,
)
from tg_companion_bot.live_runtime import RuntimeState


def _event(kind: str, **overrides) -> HermesInboundEvent:
    values = {
        "kind": kind,
        "chat_id": "777",
        "user_id": "42",
        "message_id": "101",
        "text": "Собери план",
        "callback_data": "",
    }
    values.update(overrides)
    return HermesInboundEvent(**values)


def _attention_item() -> AttentionItem:
    return AttentionItem(
        attention_id="review-1",
        title="Решить судьбу файла",
        project="Obsidian",
        path="C:/Vault/file.md",
        reason="Нужно решение",
        risk="Можно потерять контекст",
        recommended_option="keep",
        decision_options=(
            DecisionOption(id="archive", label="Архивировать", effect="Перенести в архив"),
            DecisionOption(id="keep", label="Оставить", effect="Не менять"),
        ),
    )


def test_final_message_uses_existing_hermes_completion_feedback_contract():
    state = RuntimeState()

    plan = plan_hermes_event(
        _event("message"),
        state=state,
        allowed_chat_id="777",
        allowed_user_id="42",
    )

    assert plan.ok is True
    assert plan.sends_messages is False
    action = plan.actions[0]
    assert action.kind == "send_message"
    assert action.reply_markup is None
    assert action.metadata["completion_feedback"] is True
    assert action.metadata["task_final"] is True
    assert state.pending_results["101"].summary == "Собери план"


def test_progress_explicitly_suppresses_completion_buttons():
    plan = plan_hermes_event(
        _event("progress", text="Проверяю файлы"),
        state=RuntimeState(),
        allowed_chat_id="777",
    )

    assert plan.ok is True
    assert plan.actions[0].metadata["suppress_completion_feedback"] is True
    assert plan.actions[0].metadata["task_final"] is False


def test_boundary_rejects_wrong_chat_or_user():
    state = RuntimeState()

    wrong_chat = plan_hermes_event(_event("message", chat_id="999"), state=state, allowed_chat_id="777")
    wrong_user = plan_hermes_event(
        _event("message", user_id="99"),
        state=state,
        allowed_chat_id="777",
        allowed_user_id="42",
    )

    assert wrong_chat.error == "unauthorized_source"
    assert wrong_user.error == "unauthorized_source"
    assert not state.pending_results


def test_companion_callback_returns_answer_and_edit_plans_without_sending():
    state = RuntimeState()
    plan_hermes_event(_event("message"), state=state, allowed_chat_id="777")

    callback_plan = plan_hermes_event(
        _event("callback", callback_data="companion:accept:101", text=""),
        state=state,
        allowed_chat_id="777",
    )

    assert callback_plan.ok is True
    assert [action.kind for action in callback_plan.actions] == ["answer_callback", "edit_message"]
    assert callback_plan.actions[1].reply_markup is None
    assert "101" not in state.pending_results


def test_attention_item_and_callback_share_runtime_state():
    state = RuntimeState()
    item_plan = plan_attention_item(_attention_item(), chat_id="777", state=state)

    assert item_plan.ok is True
    assert item_plan.actions[0].kind == "send_attention"
    assert item_plan.actions[0].reply_markup is not None

    callback_plan = plan_hermes_event(
        _event("callback", callback_data="attention:review-1:keep", text=""),
        state=state,
        allowed_chat_id="777",
    )

    assert callback_plan.ok is True
    assert callback_plan.actions[1].reply_markup is None
    assert state.attention_decisions["review-1"].option_id == "keep"


def test_gateway_boundary_has_no_live_framework_or_network_imports():
    source = (Path(__file__).resolve().parents[1] / "src" / "tg_companion_bot" / "hermes_gateway_adapter.py").read_text(
        encoding="utf-8"
    )

    assert "import telegram" not in source
    assert "import aiogram" not in source
    assert "gateway.platforms" not in source
    assert "start_polling" not in source


def test_stale_companion_callback_fails_closed_without_edit_plan():
    plan = plan_hermes_event(
        _event("callback", callback_data="companion:accept:missing", text=""),
        state=RuntimeState(),
        allowed_chat_id="777",
        allowed_user_id="42",
    )

    assert plan.ok is False
    assert plan.error == "stale_companion_result"
    assert plan.actions == ()
