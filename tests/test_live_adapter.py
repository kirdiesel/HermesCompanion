from pathlib import Path

from tg_companion_bot.live_adapter import (
    AdapterConfig,
    LiveRunPlan,
    build_live_run_plan,
    load_adapter_config,
)


def test_load_adapter_config_from_env_file_without_exposing_token(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BOT_TOKEN=123456:SECRET\n"
        "OBSIDIAN_VAULT=C:/AIProjects/Obsidian/One\n"
        "DEFAULT_PROJECT=TG Bot Companion\n",
        encoding="utf-8",
    )

    config = load_adapter_config(env_file)

    assert config.has_bot_token is True
    assert config.bot_token_preview == "123456:***"
    assert config.obsidian_vault == Path("C:/AIProjects/Obsidian/One")
    assert config.default_project == "TG Bot Companion"


def test_load_adapter_config_keeps_missing_token_as_not_ready(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("OBSIDIAN_VAULT=C:/Vault\n", encoding="utf-8")

    config = load_adapter_config(env_file)

    assert config.has_bot_token is False
    assert config.bot_token_preview == "<missing>"


def test_build_live_run_plan_defaults_to_dry_run_and_never_consumes_updates():
    config = AdapterConfig(
        bot_token="123456:SECRET",
        obsidian_vault=Path("C:/Vault"),
        default_project="Project",
    )

    plan = build_live_run_plan(config)

    assert isinstance(plan, LiveRunPlan)
    assert plan.mode == "dry-run"
    assert plan.can_consume_updates is False
    assert plan.can_send_messages is False
    assert plan.needs_confirmation is True
    assert "BotFather token" in plan.checks
    assert "polling conflict" in plan.risks


def test_build_live_run_plan_marks_missing_token_as_blocker():
    config = AdapterConfig(
        bot_token=None,
        obsidian_vault=Path("C:/Vault"),
        default_project="Project",
    )

    plan = build_live_run_plan(config)

    assert plan.ready is False
    assert "BOT_TOKEN is missing" in plan.blockers


def test_live_adapter_module_does_not_import_aiogram_or_telegram_frameworks():
    import sys
    import tg_companion_bot.live_adapter  # noqa: F401

    assert "aiogram" not in sys.modules
    assert "telegram" not in sys.modules
