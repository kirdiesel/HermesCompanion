import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(payload: dict, *extra_args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tg_companion_bot.smoke_cli",
            *extra_args,
        ],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    )


def test_smoke_cli_converts_text_update_to_telegram_payload_json():
    update = {
        "message": {
            "message_id": 101,
            "chat": {"id": 777},
            "from": {"id": 42},
            "text": "Собери план проекта",
        }
    }

    result = run_cli(update)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "dry_run"
    assert payload["safety"] == {
        "requires_token": False,
        "consumes_updates": False,
        "sends_messages": False,
    }
    assert payload["telegram_payload"]["chat_id"] == 777
    assert "🔎 приёмка" in payload["telegram_payload"]["text"]
    assert payload["telegram_payload"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith(
        "companion:accept:"
    )


def test_smoke_cli_rejects_unsupported_update_without_consuming_it():
    update = {"message": {"chat": {"id": 777}, "photo": [{"file_id": "abc"}]}}

    result = run_cli(update)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "unsupported_update"
    assert payload["safety"]["consumes_updates"] is False
    assert payload["safety"]["sends_messages"] is False


def test_smoke_cli_can_read_update_from_file(tmp_path):
    update_path = tmp_path / "update.json"
    update_path.write_text(
        json.dumps({"message": {"message_id": 202, "chat": {"id": 555}, "text": "Проверка"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = run_cli({}, "--input", str(update_path))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["telegram_payload"]["chat_id"] == 555
    assert payload["source"] == str(update_path)
