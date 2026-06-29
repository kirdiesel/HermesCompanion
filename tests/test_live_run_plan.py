from tg_companion_bot.live_run_plan import (
    FrameworkChoice,
    LiveRunSafetyPlan,
    choose_framework,
    build_live_run_safety_plan,
)


def test_choose_framework_prefers_aiogram_3_for_async_bot_adapter():
    choice = choose_framework()

    assert isinstance(choice, FrameworkChoice)
    assert choice.name == "aiogram"
    assert choice.major_version == 3
    assert "async" in choice.rationale.lower()
    assert "webhook" in " ".join(choice.supports).lower()
    assert choice.does_not_start_polling is True


def test_live_run_safety_plan_keeps_default_mode_dry_run_without_token_or_polling():
    plan = build_live_run_safety_plan(framework=choose_framework())

    assert isinstance(plan, LiveRunSafetyPlan)
    assert plan.mode == "dry_run"
    assert plan.requires_user_confirmation is True
    assert plan.requires_botfather_token is True
    assert plan.consumes_updates is False
    assert plan.sends_messages is False
    assert plan.allowed_without_confirmation == [
        "render_payload",
        "parse_update_fixture",
        "run_smoke_cli",
        "validate_config_without_token",
    ]
    assert "token leakage" in plan.risks
    assert "polling conflict" in plan.risks


def test_live_run_safety_plan_lists_activation_gates_in_order():
    plan = build_live_run_safety_plan(framework=choose_framework())

    assert plan.activation_gates == [
        "all_tests_green",
        "explicit_user_confirmation",
        "botfather_token_configured_outside_git",
        "no_existing_polling_conflict",
        "dry_run_payload_verified",
        "single_chat_limited_smoke",
    ]
