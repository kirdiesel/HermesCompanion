import json
import os
import subprocess
import sys
from pathlib import Path

from tg_companion_bot.smoke_cli import REAL_OBSIDIAN_ROOT, _is_real_obsidian_root


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


def write_state(path: Path, message_id: str = "101", summary: str = "Собери план проекта") -> None:
    path.write_text(
        json.dumps(
            {
                "pending_results": {
                    message_id: {
                        "chat_id": "777",
                        "message_id": message_id,
                        "summary": summary,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_safety_flags(payload: dict) -> None:
    assert payload["safety"] == {
        "requires_token": False,
        "consumes_updates": False,
        "sends_messages": False,
    }


def callback_update(action: str, message_id: int = 101) -> dict:
    return {
        "callback_query": {
            "id": "cb-1",
            "data": f"companion:{action}:{message_id}",
            "message": {
                "message_id": message_id,
                "chat": {"id": 777},
            },
        }
    }


def attention_report() -> dict:
    return {
        "chat_id": 777,
        "attention_items": [
            {
                "attention_id": "review-1",
                "title": "Решить судьбу файла",
                "project": "Obsidian",
                "path": "C:/Vault/file.md",
                "reason": "Требуется решение",
                "risk": "Можно потерять контекст",
                "decision_options": [
                    {"id": "archive", "label": "Архивировать", "effect": "Перенести в архив"},
                    {"id": "keep", "label": "Оставить", "effect": "Ничего не менять"},
                ],
            }
        ],
    }


def attention_callback(option_id: str, attention_id: str = "review-1") -> dict:
    return {
        "callback_query": {
            "id": "attention-cb-1",
            "data": f"attention:{attention_id}:{option_id}",
            "message": {"message_id": 900, "chat": {"id": 777}},
        }
    }


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
    assert_safety_flags(payload)
    assert payload["telegram_payload"]["chat_id"] == 777
    assert "🔎 приёмка" in payload["telegram_payload"]["text"]
    assert payload["telegram_payload"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith(
        "companion:accept:"
    )


def test_smoke_cli_writes_windows_safe_ascii_json_with_russian_text_and_emoji():
    update = {
        "message": {
            "message_id": 101,
            "chat": {"id": 777},
            "text": "Собери план проекта",
        }
    }

    result = run_cli(update)

    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stdout.encode("ascii").decode("ascii")
    payload = json.loads(result.stdout)
    assert "Собери план проекта" in payload["telegram_payload"]["text"]
    assert "🔎 приёмка" in payload["telegram_payload"]["text"]


def test_smoke_cli_rejects_unsupported_update_without_consuming_it():
    update = {"message": {"chat": {"id": 777}, "photo": [{"file_id": "abc"}]}}

    result = run_cli(update)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "unsupported_update"
    assert_safety_flags(payload)
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


def test_smoke_cli_converts_report_attention_items_to_separate_telegram_payloads():
    report = {
        "chat_id": 777,
        "attention_items": [
            {
                "attention_id": "rename-node-1",
                "title": "Переименовать технический узел",
                "project": "Obsidian",
                "path": "C:/Vault/00_PROJECT_INDEX.md",
                "reason": "Видимый узел графа на английском",
                "risk": "Можно сломать ссылки при переименовании",
                "decision_options": [
                    {"id": "rename_ru", "label": "Переименовать по-русски", "effect": "Обновить имя и ссылки"},
                    {"id": "keep", "label": "Оставить как есть", "effect": "Не менять файл"},
                ],
            },
            {
                "attention_id": "draft-1",
                "title": "Решить судьбу черновика",
                "project": "Codex",
                "path": "C:/Vault/next_codex_steps.md",
                "reason": "Черновик больше не активен",
                "risk": "Можно потерять контекст",
                "decision_options": [
                    {"id": "archive", "label": "Архивировать", "effect": "Перенести в архив"},
                    {"id": "keep", "label": "Оставить как есть", "effect": "Не менять файл"},
                ],
            },
        ],
    }

    result = run_cli(report)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "dry_run"
    assert payload["kind"] == "attention_items"
    assert_safety_flags(payload)
    assert len(payload["telegram_payloads"]) == 2
    first = payload["telegram_payloads"][0]
    assert first["chat_id"] == 777
    assert first["text"].startswith("🔴 Требует внимания: Переименовать технический узел")
    assert "attention_items:" not in first["text"]
    keyboard = first["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["text"] == "Переименовать по-русски"
    assert keyboard[0][0]["callback_data"] == "attention:rename-node-1:rename_ru"
    assert keyboard[1][0]["text"] == "Оставить как есть"


def test_attention_report_with_state_saves_pending_items(tmp_path):
    state_path = tmp_path / "state.json"

    result = run_cli(attention_report(), "--state", str(state_path))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["state"]["pending_attention_ids"] == ["review-1"]
    state = read_state(state_path)
    assert state["pending_attention_items"]["review-1"]["title"] == "Решить судьбу файла"


def test_attention_callback_applies_once_and_removes_buttons(tmp_path):
    state_path = tmp_path / "state.json"
    assert run_cli(attention_report(), "--state", str(state_path)).returncode == 0

    result = run_cli(attention_callback("keep"), "--state", str(state_path))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert_safety_flags(payload)
    assert payload["attention_result"] == {
        "attention_id": "review-1",
        "selected_option_id": "keep",
        "selected_label": "Оставить",
        "applied": True,
        "duplicate": False,
    }
    assert payload["telegram_payload"]["reply_markup"] is None
    assert payload["telegram_payload"]["remove_keyboard"] is True
    state = read_state(state_path)
    assert state["pending_attention_items"] == {}
    assert state["attention_decisions"]["review-1"]["option_id"] == "keep"


def test_attention_callback_duplicate_is_idempotent(tmp_path):
    state_path = tmp_path / "state.json"
    assert run_cli(attention_report(), "--state", str(state_path)).returncode == 0
    assert run_cli(attention_callback("keep"), "--state", str(state_path)).returncode == 0

    duplicate = run_cli(attention_callback("keep"), "--state", str(state_path))

    assert duplicate.returncode == 0, duplicate.stderr
    payload = json.loads(duplicate.stdout)
    assert payload["attention_result"]["applied"] is False
    assert payload["attention_result"]["duplicate"] is True
    assert "уже было принято" in payload["telegram_payload"]["text"]


def test_attention_callback_rejects_conflicting_second_decision(tmp_path):
    state_path = tmp_path / "state.json"
    assert run_cli(attention_report(), "--state", str(state_path)).returncode == 0
    assert run_cli(attention_callback("keep"), "--state", str(state_path)).returncode == 0

    conflict = run_cli(attention_callback("archive"), "--state", str(state_path))

    assert conflict.returncode == 2
    payload = json.loads(conflict.stdout)
    assert payload["error"] == "attention_already_resolved"
    assert payload["attention_result"]["selected_option_id"] == "keep"


def test_attention_callback_rejects_stale_item(tmp_path):
    state_path = tmp_path / "state.json"

    stale = run_cli(attention_callback("keep", attention_id="missing"), "--state", str(state_path))

    assert stale.returncode == 2
    payload = json.loads(stale.stdout)
    assert payload["error"] == "stale_attention_callback"
    assert_safety_flags(payload)


def test_message_update_with_state_saves_pending_result(tmp_path):
    state_path = tmp_path / "state.json"
    update = {
        "message": {
            "message_id": 101,
            "chat": {"id": 777},
            "text": "Собери план проекта",
        }
    }

    result = run_cli(update, "--state", str(state_path))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert_safety_flags(payload)
    assert payload["state"]["pending_result_ids"] == ["101"]
    state = read_state(state_path)
    assert state["pending_results"]["101"] == {
        "chat_id": "777",
        "message_id": "101",
        "summary": "Собери план проекта",
    }


def test_callback_accept_with_state_removes_pending_result(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(state_path)

    result = run_cli(callback_update("accept"), "--state", str(state_path))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert_safety_flags(payload)
    assert payload["callback_result"]["action"] == "accept"
    assert payload["callback_result"]["status"] == "✅ готово"
    assert payload["callback_result"]["remove_keyboard"] is True
    assert payload["telegram_payload"]["remove_keyboard"] is True
    assert "inline_keyboard" not in payload["telegram_payload"]
    assert read_state(state_path)["pending_results"] == {}


def test_callback_revise_with_state_keeps_pending_result(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(state_path)

    result = run_cli(callback_update("revise"), "--state", str(state_path))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert_safety_flags(payload)
    assert payload["callback_result"]["action"] == "revise"
    assert payload["callback_result"]["status"] == "▶️ выполняется"
    assert "▶️ выполняется" in payload["telegram_payload"]["text"]
    assert "101" in read_state(state_path)["pending_results"]


def test_callback_next_with_state_keeps_pending_result(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(state_path)

    result = run_cli(callback_update("next"), "--state", str(state_path))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert_safety_flags(payload)
    assert payload["callback_result"]["action"] == "next"
    assert payload["callback_result"]["status"] == "🔎 приёмка"
    assert payload["callback_result"]["next_intent"] == "show_next_step"
    assert payload["callback_result"]["remove_keyboard"] is True
    assert payload["telegram_payload"]["remove_keyboard"] is True
    assert "101" in read_state(state_path)["pending_results"]


def test_callback_without_pending_state_returns_stale_error(tmp_path):
    state_path = tmp_path / "state.json"

    result = run_cli(callback_update("accept"), "--state", str(state_path))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["callback_result"]["error"] == "stale_companion_result"
    assert not state_path.exists() or read_state(state_path)["pending_results"] == {}


def test_callback_from_other_chat_does_not_apply_pending_result(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(state_path)
    update = callback_update("accept")
    update["callback_query"]["message"]["chat"]["id"] = 999

    result = run_cli(update, "--state", str(state_path))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["callback_result"]["error"] == "callback_chat_mismatch"
    assert "101" in read_state(state_path)["pending_results"]


def test_real_vault_guard_blocks_root_and_descendants():
    assert _is_real_obsidian_root(str(REAL_OBSIDIAN_ROOT)) is True
    assert _is_real_obsidian_root(str(REAL_OBSIDIAN_ROOT / "03_Проекты" / "smoke")) is True


def test_callback_accept_with_obsidian_root_writes_to_temp_vault(tmp_path):
    state_path = tmp_path / "state.json"
    vault_root = tmp_path / "vault"
    write_state(state_path, summary="Итог для записи в Obsidian")

    result = run_cli(
        callback_update("accept"),
        "--state",
        str(state_path),
        "--obsidian-root",
        str(vault_root),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert_safety_flags(payload)
    assert payload["persistence"] is not None
    created_files = [Path(path) for path in payload["created_files"]]
    assert len(created_files) == 3
    assert all(path.exists() for path in created_files)
    assert payload["persistence"]["event_id"] == "101"
    assert payload["persistence"]["duplicate"] is False
    assert "_tg-companion" in created_files[0].parts
    assert "Итог для записи в Obsidian" in created_files[0].read_text(encoding="utf-8")
    assert read_state(state_path)["pending_results"] == {}


def test_invalid_state_file_returns_clear_error(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{not-json", encoding="utf-8")
    update = {
        "message": {
            "message_id": 101,
            "chat": {"id": 777},
            "text": "Собери план проекта",
        }
    }

    result = run_cli(update, "--state", str(state_path))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_state"
    assert_safety_flags(payload)
