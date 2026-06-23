from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, TextIO

from .live_runtime import RuntimeState
from .telegram_framework_adapter import build_send_payload


SAFETY = {
    "requires_token": False,
    "consumes_updates": False,
    "sends_messages": False,
}


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


def run_smoke_cli(argv: Optional[Iterable[str]] = None, *, stdin: TextIO = sys.stdin) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run Telegram-like update through tg-companion-bot runtime without token/polling."
    )
    parser.add_argument("--input", help="Path to Telegram-like update JSON. Defaults to stdin.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        update, source = _read_json(input_path=args.input, stdin=stdin)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(
            json.dumps(
                {
                    "ok": False,
                    "mode": "dry_run",
                    "source": args.input or "stdin",
                    "error": "invalid_json",
                    "detail": str(exc),
                    "safety": SAFETY,
                },
                ensure_ascii=False,
            )
        )
        return 2

    prepared = build_send_payload(update, state=RuntimeState())
    if prepared is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "mode": "dry_run",
                    "source": source,
                    "error": "unsupported_update",
                    "safety": SAFETY,
                },
                ensure_ascii=False,
            )
        )
        return 2

    telegram_payload = asdict(prepared.payload)
    telegram_payload["chat_id"] = _json_chat_id(prepared.chat_id)
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "dry_run",
                "source": source,
                "safety": SAFETY,
                "telegram_payload": telegram_payload,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> None:
    raise SystemExit(run_smoke_cli())


if __name__ == "__main__":
    main()
