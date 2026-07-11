from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .attention_items import AttentionItem, DecisionOption, attention_item_to_telegram_payload
from .state_codec import attention_item_from_dict


SAFETY = {
    "requires_token": False,
    "consumes_updates": False,
    "sends_messages": False,
}

_KNOWN_OPTIONS = {
    "Оставить как есть": ("keep", "Ничего не менять"),
    "Показать подробнее": ("details", "Показать детали отчёта"),
    "Отложить": ("defer", "Вернуться к вопросу позже"),
    "Архивировать вместо удаления": ("archive", "Архивировать без удаления"),
    "Исключить из активного графа, но не удалять": (
        "exclude",
        "Исключить из активного графа без удаления",
    ),
}

_RISK_BY_TYPE = {
    "unresolved_wikilinks": "Автоправка может связать заметки с неверными смысловыми узлами.",
    "duplicate_readmes": "README в разных контекстах могут быть самостоятельными документами, а не дублями.",
}

_RECOMMENDED_BY_TYPE = {
    "unresolved_wikilinks": "details",
    "duplicate_readmes": "keep",
}


def load_nightly_attention(path: Path | str) -> tuple[AttentionItem, ...]:
    report_path = Path(path)
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    raw_items = raw.get("attention_items") if isinstance(raw, Mapping) else raw
    if not isinstance(raw_items, list):
        raise ValueError("nightly attention report must be a list or contain attention_items")

    report_date = _report_date(report_path)
    items = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            raise ValueError(f"attention item {index} must be an object")
        if raw_item.get("attention_id"):
            items.append(attention_item_from_dict(raw_item))
        else:
            items.append(_legacy_item(raw_item, report_path=report_path, report_date=report_date))
    return tuple(items)


def build_dry_run_report(path: Path | str, *, chat_id: str) -> dict[str, Any]:
    items = load_nightly_attention(path)
    payloads = []
    for item in items:
        payload = asdict(attention_item_to_telegram_payload(item))
        payload["chat_id"] = int(chat_id) if str(chat_id).lstrip("-").isdigit() else str(chat_id)
        payloads.append(payload)
    return {
        "ok": True,
        "mode": "dry_run",
        "kind": "nightly_attention_items",
        "source": str(Path(path)),
        "safety": SAFETY,
        "attention_items": [asdict(item) for item in items],
        "telegram_payloads": payloads,
    }


def _legacy_item(
    raw: Mapping[str, Any],
    *,
    report_path: Path,
    report_date: date,
) -> AttentionItem:
    item_type = str(raw.get("type") or "attention")
    title = str(raw.get("title") or "Требуется решение").strip()
    detail = str(raw.get("detail") or "Автоматическое изменение не выполнялось.").strip()
    raw_options = raw.get("options")
    if not isinstance(raw_options, Sequence) or isinstance(raw_options, (str, bytes)):
        raise ValueError(f"nightly attention item {item_type!r} has no options")
    options = tuple(_option(str(label)) for label in raw_options if str(label).strip())
    if not options:
        raise ValueError(f"nightly attention item {item_type!r} has no valid options")

    recommended = _RECOMMENDED_BY_TYPE.get(item_type, options[0].id)
    if recommended not in {option.id for option in options}:
        recommended = options[0].id
    return AttentionItem(
        attention_id=_weekly_attention_id(report_date, item_type, title),
        title=title,
        project="Obsidian",
        path=f"Отчёт ночного аудита: {report_date.isoformat()}.md",
        reason=detail,
        risk=_RISK_BY_TYPE.get(
            item_type,
            "Автоматическое действие без проверки может изменить пользовательские данные.",
        ),
        recommended_option=recommended,
        decision_options=options,
    )


def _option(label: str) -> DecisionOption:
    known = _KNOWN_OPTIONS.get(label)
    if known is not None:
        option_id, effect = known
        return DecisionOption(id=option_id, label=label, effect=effect)
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:8]
    return DecisionOption(id=f"option-{digest}", label=label, effect=label)


def _report_date(path: Path) -> date:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
    if match:
        return date.fromisoformat(match.group(1))
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def _weekly_attention_id(report_date: date, item_type: str, title: str) -> str:
    iso = report_date.isocalendar()
    slug = re.sub(r"[^a-z0-9]+", "-", item_type.lower()).strip("-") or "item"
    digest = hashlib.sha256(f"{item_type}\n{title}".encode("utf-8")).hexdigest()[:6]
    return f"obs-{iso.year}w{iso.week:02d}-{slug[:20]}-{digest}"


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a nightly Obsidian attention report to Telegram-ready dry-run payloads."
    )
    parser.add_argument("--input", required=True, help="Path to attention_items_YYYY-MM-DD.json")
    parser.add_argument("--chat-id", required=True, help="Target chat id included in dry-run payloads")
    args = parser.parse_args(argv)
    try:
        report = build_dry_run_report(args.input, chat_id=args.chat_id)
    except Exception as error:
        report = {
            "ok": False,
            "mode": "dry_run",
            "kind": "nightly_attention_items",
            "source": args.input,
            "error": "invalid_nightly_attention_report",
            "detail": str(error),
            "safety": SAFETY,
        }
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["ok"] else 2


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
