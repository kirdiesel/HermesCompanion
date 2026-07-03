from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, TextIO

from .attention_items import (
    AttentionItem,
    attention_item_to_telegram_payload,
)
from .callbacks import handle_callback
from .live_runtime import (
    RuntimeState,
    handle_runtime_attention_callback,
    handle_runtime_callback,
)
from .state_codec import (
    StateCodecError,
    attention_item_from_dict,
    runtime_state_from_dict,
    runtime_state_to_dict,
)
from .telegram_framework_adapter import adapt_callback_query_update, build_send_payload


SAFETY = {
    "requires_token": False,
    "consumes_updates": False,
    "sends_messages": False,
}

REAL_OBSIDIAN_ROOT = Path("C:/AIProjects/Obsidian/One").resolve()


class StateLoadError(StateCodecError):
    pass


def _read_json(*, input_path: Optional[str], stdin: TextIO) -> tuple[Dict[str, Any], str]:
    if input_path:
        raw = Path(input_path).read_text(encoding="utf-8")
        source = input_path
    else:
        raw = stdin.read()
        source = "stdin"

    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ValueError("update JSON must be an object")
    return data, source


def _json_chat_id(chat_id: str) -> str | int:
    return int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id


def _write_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True))


def _load_state(*, state_path: Optional[str], obsidian_root: Optional[str]) -> RuntimeState:
    state = RuntimeState(obsidian_root=Path(obsidian_root) if obsidian_root else None)
    if state_path is None:
        return state

    path = Path(state_path)
    if not path.exists():
        return state

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StateLoadError(str(exc)) from exc

    try:
        return runtime_state_from_dict(data, obsidian_root=obsidian_root)
    except StateCodecError as exc:
        raise StateLoadError(str(exc)) from exc


def _save_state(*, state_path: Optional[str], state: RuntimeState) -> None:
    if state_path is None:
        return

    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = runtime_state_to_dict(state)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _state_summary(state: RuntimeState) -> Dict[str, Any]:
    return {
        "pending_result_ids": sorted(state.pending_results),
        "pending_results_count": len(state.pending_results),
        "companion_decision_ids": sorted(state.companion_decisions),
        "companion_decisions_count": len(state.companion_decisions),
        "pending_attention_ids": sorted(state.pending_attention_items),
        "pending_attention_count": len(state.pending_attention_items),
        "attention_decision_ids": sorted(state.attention_decisions),
        "attention_decisions_count": len(state.attention_decisions),
    }


def _telegram_payload_json(payload: Any, chat_id: str) -> Dict[str, Any]:
    telegram_payload = asdict(payload)
    telegram_payload["chat_id"] = _json_chat_id(chat_id)
    return telegram_payload


def _attention_item_from_json(data: Dict[str, Any]) -> AttentionItem:
    return attention_item_from_dict(data)


def _handle_attention_items_report(
    update: Dict[str, Any],
    *,
    state: RuntimeState,
    source: str,
    state_path: Optional[str],
) -> tuple[bool, int]:
    raw_items = update.get("attention_items")
    if not isinstance(raw_items, list):
        return False, 0

    chat_id = update.get("chat_id")
    if chat_id is None:
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": source,
                "kind": "attention_items",
                "error": "missing_chat_id",
                "safety": SAFETY,
            }
        )
        return True, 2

    telegram_payloads = []
    skipped_resolved_ids = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue
        try:
            item = _attention_item_from_json(raw_item)
        except (KeyError, TypeError, ValueError) as exc:
            _write_json(
                {
                    "ok": False,
                    "mode": "dry_run",
                    "source": source,
                    "kind": "attention_items",
                    "error": "invalid_attention_item",
                    "item_index": index,
                    "detail": str(exc),
                    "safety": SAFETY,
                    "state": _state_summary(state),
                }
            )
            return True, 2
        if item.attention_id in state.attention_decisions:
            skipped_resolved_ids.append(item.attention_id)
            continue
        state.pending_attention_items[item.attention_id] = item
        payload = asdict(attention_item_to_telegram_payload(item))
        payload["chat_id"] = _json_chat_id(str(chat_id))
        telegram_payloads.append(payload)

    _save_state(state_path=state_path, state=state)
    _write_json(
        {
            "ok": True,
            "mode": "dry_run",
            "source": source,
            "kind": "attention_items",
            "safety": SAFETY,
            "telegram_payloads": telegram_payloads,
            "skipped_resolved_ids": skipped_resolved_ids,
            "state": _state_summary(state),
        }
    )
    return True, 0


def _attention_telegram_payload(callback: Any, payload: Any) -> Dict[str, Any]:
    return {
        "chat_id": _json_chat_id(callback.chat_id),
        "message_id": _json_chat_id(callback.message_id) if callback.message_id else callback.message_id,
        "text": payload.text,
        "parse_mode": None,
        "disable_web_page_preview": True,
        "reply_markup": payload.reply_markup,
        "remove_keyboard": True,
    }


def _handle_attention_callback_update(
    update: Dict[str, Any],
    *,
    state: RuntimeState,
    source: str,
    state_path: Optional[str],
) -> tuple[bool, int]:
    callback = adapt_callback_query_update(update)
    if callback is None or not callback.callback_data.startswith("attention:"):
        return False, 0

    runtime_result = handle_runtime_attention_callback(callback.callback_data, state=state)
    if runtime_result.status == "invalid":
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": source,
                "kind": "attention_decision",
                "error": "invalid_attention_callback",
                "safety": SAFETY,
                "state": _state_summary(state),
            }
        )
        return True, 2

    if runtime_result.status in {"duplicate", "conflict"}:
        record = runtime_result.record
        assert record is not None and runtime_result.payload is not None
        output = {
            "ok": runtime_result.ok,
            "mode": "dry_run",
            "source": source,
            "kind": "attention_decision",
            "error": runtime_result.error,
            "safety": SAFETY,
            "callback_query_id": callback.callback_query_id,
            "callback_data": callback.callback_data,
            "attention_result": {
                "attention_id": record.attention_id,
                "selected_option_id": record.option_id,
                "selected_label": record.selected_label,
                "applied": False,
                "duplicate": runtime_result.duplicate,
            },
            "telegram_payload": _attention_telegram_payload(callback, runtime_result.payload),
            "state": _state_summary(state),
        }
        _write_json(output)
        return True, 0 if runtime_result.ok else 2

    if runtime_result.status == "stale":
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": source,
                "kind": "attention_decision",
                "error": "stale_attention_callback",
                "safety": SAFETY,
                "callback_query_id": callback.callback_query_id,
                "callback_data": callback.callback_data,
                "state": _state_summary(state),
            }
        )
        return True, 2

    if runtime_result.status == "unknown_option":
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": source,
                "kind": "attention_decision",
                "error": "unknown_attention_option",
                "safety": SAFETY,
                "callback_query_id": callback.callback_query_id,
                "callback_data": callback.callback_data,
                "telegram_payload": _attention_telegram_payload(callback, runtime_result.payload),
                "state": _state_summary(state),
            }
        )
        return True, 2

    record = runtime_result.record
    assert record is not None and runtime_result.payload is not None
    _save_state(state_path=state_path, state=state)
    _write_json(
        {
            "ok": True,
            "mode": "dry_run",
            "source": source,
            "kind": "attention_decision",
            "safety": SAFETY,
            "callback_query_id": callback.callback_query_id,
            "callback_data": callback.callback_data,
            "attention_result": {
                "attention_id": record.attention_id,
                "selected_option_id": record.option_id,
                "selected_label": record.selected_label,
                "applied": True,
                "duplicate": False,
            },
            "telegram_payload": _attention_telegram_payload(callback, runtime_result.payload),
            "state": _state_summary(state),
        }
    )
    return True, 0


def _callback_payload_text(status: Optional[str], follow_up: str, rendered_text: Optional[str]) -> str:
    parts = []
    if rendered_text:
        parts.append(rendered_text)
    elif status:
        parts.append(f"Статус: {status}")
    if follow_up:
        parts.append(follow_up)
    return "\n\n".join(parts)


def _path_payload(path: Path) -> str:
    return str(path)


def _persistence_payload(persistence: Any) -> Optional[Dict[str, Any]]:
    if persistence is None:
        return None
    return {
        "project_note": _path_payload(persistence.project_note),
        "decisions_log": _path_payload(persistence.decisions_log),
        "decision_note": _path_payload(persistence.decision_note),
        "event_id": persistence.event_id,
        "duplicate": persistence.duplicate,
    }


def _is_real_obsidian_root(path: Optional[str]) -> bool:
    return path is not None and Path(path).resolve() == REAL_OBSIDIAN_ROOT


def _handle_callback_update(
    update: Dict[str, Any],
    *,
    state: RuntimeState,
    source: str,
    state_path: Optional[str],
    obsidian_root: Optional[str],
) -> tuple[bool, int]:
    callback = adapt_callback_query_update(update)
    if callback is None:
        return False, 0

    callback_result = handle_callback(callback.callback_data)
    if callback_result.task_id is None:
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": source,
                "error": "invalid_callback",
                "safety": SAFETY,
                "callback_result": asdict(callback_result),
                "state": _state_summary(state),
            }
        )
        return True, 2

    if callback_result.next_intent in {"run_optimal_next_step", "run_recommendation"} and _is_real_obsidian_root(
        obsidian_root
    ):
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": source,
                "error": "real_vault_write_blocked",
                "detail": "Use a test vault for --obsidian-root unless real vault write is explicitly confirmed.",
                "safety": SAFETY,
                "state": _state_summary(state),
            }
        )
        return True, 2

    pending_found = callback_result.task_id in state.pending_results
    runtime_result = handle_runtime_callback(callback.callback_data, state=state)
    _save_state(state_path=state_path, state=state)

    rendered_text = runtime_result.rendered.text if runtime_result.rendered is not None else None
    telegram_payload: Dict[str, Any] = {
        "chat_id": _json_chat_id(callback.chat_id),
        "message_id": _json_chat_id(callback.message_id) if callback.message_id else callback.message_id,
        "text": _callback_payload_text(callback_result.status, runtime_result.follow_up, rendered_text),
        "parse_mode": None,
        "disable_web_page_preview": True,
    }
    if callback_result.remove_keyboard:
        telegram_payload["remove_keyboard"] = True

    persistence = _persistence_payload(runtime_result.persistence)
    output = {
        "ok": True,
        "mode": "dry_run",
        "source": source,
        "safety": SAFETY,
        "callback_query_id": callback.callback_query_id,
        "callback_data": callback.callback_data,
        "callback_result": {
            "task_id": callback_result.task_id,
            "action": runtime_result.action.value if runtime_result.action is not None else None,
            "status": callback_result.status,
            "remove_keyboard": callback_result.remove_keyboard,
            "next_intent": callback_result.next_intent,
            "follow_up": runtime_result.follow_up,
            "pending_result_found": pending_found,
            "applied": runtime_result.applied,
            "duplicate": runtime_result.duplicate,
            "error": runtime_result.error,
        },
        "telegram_payload": telegram_payload,
        "persistence": persistence,
        "created_files": (
            [
                persistence["project_note"],
                persistence["decisions_log"],
                persistence["decision_note"],
            ]
            if persistence
            else []
        ),
        "state": _state_summary(state),
    }
    _write_json(output)
    return True, 0


def run_smoke_cli(argv: Optional[Iterable[str]] = None, *, stdin: TextIO = sys.stdin) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run Telegram-like update through tg-companion-bot runtime without token/polling."
    )
    parser.add_argument("--input", help="Path to Telegram-like update JSON. Defaults to stdin.")
    parser.add_argument("--state", help="Path to smoke CLI JSON state file.")
    parser.add_argument("--obsidian-root", help="Test Obsidian vault root used only for valid accept callbacks.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        update, source = _read_json(input_path=args.input, stdin=stdin)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": args.input or "stdin",
                "error": "invalid_json",
                "detail": str(exc),
                "safety": SAFETY,
            }
        )
        return 2

    try:
        state = _load_state(state_path=args.state, obsidian_root=args.obsidian_root)
    except StateLoadError as exc:
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": source,
                "error": "invalid_state",
                "detail": str(exc),
                "safety": SAFETY,
            }
        )
        return 2

    handled_attention, attention_exit = _handle_attention_items_report(
        update,
        state=state,
        source=source,
        state_path=args.state,
    )
    if handled_attention:
        return attention_exit

    handled_attention_callback, attention_callback_exit = _handle_attention_callback_update(
        update,
        state=state,
        source=source,
        state_path=args.state,
    )
    if handled_attention_callback:
        return attention_callback_exit

    handled_callback, callback_exit = _handle_callback_update(
        update,
        state=state,
        source=source,
        state_path=args.state,
        obsidian_root=args.obsidian_root,
    )
    if handled_callback:
        return callback_exit

    prepared = build_send_payload(update, state=state)
    if prepared is None:
        _write_json(
            {
                "ok": False,
                "mode": "dry_run",
                "source": source,
                "error": "unsupported_update",
                "safety": SAFETY,
                "state": _state_summary(state),
            }
        )
        return 2

    _save_state(state_path=args.state, state=state)
    _write_json(
        {
            "ok": True,
            "mode": "dry_run",
            "source": source,
            "safety": SAFETY,
            "telegram_payload": _telegram_payload_json(prepared.payload, prepared.chat_id),
            "state": _state_summary(state),
        }
    )
    return 0


def main() -> None:
    raise SystemExit(run_smoke_cli())


if __name__ == "__main__":
    main()
