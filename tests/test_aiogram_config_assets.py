from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_aiogram_dependency_declared_without_installing_live_runtime():
    requirements = PROJECT_ROOT / "requirements.txt"

    assert requirements.exists()
    lines = [line.strip() for line in requirements.read_text(encoding="utf-8").splitlines()]
    assert any(line.startswith("aiogram>=3") for line in lines)
    assert "python-dotenv>=1" in lines


def test_env_example_documents_token_storage_without_real_token():
    env_example = PROJECT_ROOT / ".env.example"

    assert env_example.exists()
    content = env_example.read_text(encoding="utf-8")
    assert "TG_COMPANION_BOT_TOKEN=" in content
    assert "TG_COMPANION_ALLOWED_CHAT_ID=" in content
    assert "DRY_RUN=true" in content
    assert "123456:" not in content
    assert "botfather" in content.lower()
    assert "do not commit" in content.lower()


def test_live_smoke_runbook_requires_dry_run_and_single_chat_before_polling():
    runbook = PROJECT_ROOT / "docs" / "live_run_aiogram3.md"

    assert runbook.exists()
    content = runbook.read_text(encoding="utf-8").lower()
    assert "aiogram 3" in content
    assert "dry-run" in content
    assert "single-chat" in content
    assert "polling conflict" in content
    assert "botfather" in content
    assert "do not commit" in content
    assert "python -m tg_companion_bot.smoke_cli" in content


def test_real_env_file_is_not_present_in_repository_tree():
    assert not (PROJECT_ROOT / ".env").exists()
