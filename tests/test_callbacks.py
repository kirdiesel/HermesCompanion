from tg_companion_bot.callbacks import CallbackAction, CallbackDecision, parse_callback_data, handle_callback


def test_parse_supported_callback_actions():
    assert parse_callback_data("companion:accept:task-1") == CallbackDecision(
        action=CallbackAction.ACCEPT,
        task_id="task-1",
    )
    assert parse_callback_data("companion:revise:task-2").action is CallbackAction.REVISE
    assert parse_callback_data("companion:next:task-3").action is CallbackAction.NEXT


def test_reject_invalid_callback_data():
    assert parse_callback_data("other:accept:task-1") is None
    assert parse_callback_data("companion:delete:task-1") is None
    assert parse_callback_data("companion:accept") is None
    assert parse_callback_data("") is None


def test_accept_callback_marks_done_and_runs_recommendation():
    result = handle_callback("companion:accept:task-1", has_recommendation=True)

    assert result.task_id == "task-1"
    assert result.status == "✅ готово"
    assert result.remove_keyboard is True
    assert result.next_intent == "run_recommendation"
    assert "Результат принят" in result.user_message


def test_accept_without_recommendation_runs_optimal_next_step():
    result = handle_callback("companion:accept:task-1", has_recommendation=False)

    assert result.status == "✅ готово"
    assert result.next_intent == "run_optimal_next_step"


def test_revise_callback_returns_to_work_without_done():
    result = handle_callback("companion:revise:task-1")

    assert result.status == "▶️ выполняется"
    assert result.remove_keyboard is True
    assert result.next_intent == "await_revision_instructions"
    assert "дорабат" in result.user_message.lower()
    assert "один короткий вопрос" in result.user_message.lower()


def test_next_callback_keeps_review_and_requests_next_step():
    result = handle_callback("companion:next:task-1")

    assert result.status == "🔎 приёмка"
    assert result.remove_keyboard is True
    assert result.next_intent == "show_next_step"


def test_unknown_callback_is_safe_noop():
    result = handle_callback("invalid")

    assert result.status is None
    assert result.remove_keyboard is False
    assert result.next_intent == "noop"
    assert "Ничего не изменено" in result.user_message
