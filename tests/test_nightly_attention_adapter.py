import json
from datetime import date
from pathlib import Path

from tg_companion_bot.attention_items import build_attention_callback_data
from tg_companion_bot.nightly_attention_adapter import (
    build_dry_run_report,
    load_nightly_attention,
)


def write_report(path: Path, *, count: int = 25) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "type": "unresolved_wikilinks",
                    "title": "Есть неразрешённые wikilink",
                    "detail": f"Количество: {count}. Автоправку не делал.",
                    "options": ["Оставить как есть", "Показать подробнее", "Отложить"],
                },
                {
                    "type": "duplicate_readmes",
                    "title": "Есть несколько README.md в разных контекстах",
                    "detail": "Количество: 9. Переименование только после приёмки.",
                    "options": ["Оставить как есть", "Показать подробнее", "Отложить"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_real_nightly_report_shape_adapts_to_companion_attention_items(tmp_path: Path):
    path = tmp_path / "attention_items_2026-07-10.json"
    write_report(path)

    items = load_nightly_attention(path)

    assert len(items) == 2
    assert items[0].project == "Obsidian"
    assert items[0].recommended_option == "details"
    assert "C:\\" not in items[0].path
    assert [option.id for option in items[0].decision_options] == ["keep", "details", "defer"]
    assert "Автоправка" in items[0].risk
    for item in items:
        for option in item.decision_options:
            assert len(build_attention_callback_data(item.attention_id, option.id).encode("utf-8")) <= 64


def test_noncritical_attention_id_is_stable_within_week_and_changes_next_week(tmp_path: Path):
    first = tmp_path / "attention_items_2026-07-09.json"
    second = tmp_path / "attention_items_2026-07-10.json"
    next_week = tmp_path / "attention_items_2026-07-16.json"
    write_report(first, count=20)
    write_report(second, count=25)
    write_report(next_week, count=30)

    first_id = load_nightly_attention(first)[0].attention_id
    second_id = load_nightly_attention(second)[0].attention_id
    next_week_id = load_nightly_attention(next_week)[0].attention_id

    assert date(2026, 7, 9).isocalendar().week == date(2026, 7, 10).isocalendar().week
    assert first_id == second_id
    assert next_week_id != first_id


def test_dry_run_report_builds_telegram_payloads_without_token_or_send(tmp_path: Path):
    path = tmp_path / "attention_items_2026-07-10.json"
    write_report(path)

    report = build_dry_run_report(path, chat_id="777")

    assert report["ok"] is True
    assert report["safety"] == {
        "requires_token": False,
        "consumes_updates": False,
        "sends_messages": False,
    }
    assert len(report["telegram_payloads"]) == 2
    assert report["telegram_payloads"][0]["chat_id"] == 777
    assert report["telegram_payloads"][0]["reply_markup"]["inline_keyboard"]
