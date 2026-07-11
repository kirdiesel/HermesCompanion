from tg_companion_bot.attention_items import (
    AttentionItem,
    DecisionOption,
    apply_attention_decision,
    attention_item_to_telegram_payload,
    build_attention_callback_data,
    decision_record_from_result,
    parse_attention_callback_data,
    recorded_decision_payload,
)


def test_attention_item_renders_as_separate_message_with_decision_buttons():
    item = AttentionItem(
        attention_id="obsidian-review-001",
        title="Решить судьбу черновика next_codex_steps",
        project="Hermes Telegram Interface",
        path="C:/AIProjects/Obsidian/One/draft.md",
        reason="Черновик выглядит устаревшим",
        risk="Можно потерять полезный контекст",
        recommended_option="accept",
        decision_options=(
            DecisionOption(id="accept", label="Принять предложение", effect="Архивировать черновик"),
            DecisionOption(id="keep", label="Оставить как есть", effect="Ничего не менять"),
            DecisionOption(id="details", label="Показать подробнее", effect="Показать детали"),
        ),
    )

    payload = attention_item_to_telegram_payload(item)

    assert payload.text.startswith("🔴 Требует внимания: Решить судьбу черновика next_codex_steps")
    assert "Путь: C:/AIProjects/Obsidian/One/draft.md" in payload.text
    assert "Риск: Можно потерять полезный контекст" in payload.text
    assert "Рекомендация: Принять предложение" in payload.text
    assert "- Архивировать" not in payload.text
    assert payload.reply_markup == {
        "inline_keyboard": [
            [{"text": "Принять предложение", "callback_data": "attention:obsidian-review-001:accept"}],
            [{"text": "Оставить как есть", "callback_data": "attention:obsidian-review-001:keep"}],
            [{"text": "Показать подробнее", "callback_data": "attention:obsidian-review-001:details"}],
        ]
    }


def test_attention_callback_data_rejects_oversized_payloads():
    too_long_id = "x" * 80

    try:
        build_attention_callback_data(too_long_id, "accept")
    except ValueError as exc:
        assert "64 bytes" in str(exc)
    else:
        raise AssertionError("Expected oversized callback data to be rejected")


def test_parse_attention_callback_data_rejects_invalid_shapes():
    parsed = parse_attention_callback_data("attention:review-1:keep")

    assert parsed is not None
    assert parsed.attention_id == "review-1"
    assert parsed.option_id == "keep"
    assert parse_attention_callback_data("other:review-1:keep") is None
    assert parse_attention_callback_data("attention:review-1") is None


def test_apply_attention_decision_removes_buttons_and_records_choice():
    item = AttentionItem(
        attention_id="review-2",
        title="Русифицировать имя daily context reflection brief",
        project="Hermes Telegram Interface",
        path="C:/vault/daily context reflection brief.md",
        reason="Английское имя видно в графе",
        risk="Название может быть устойчивым исключением",
        recommended_option="rename_ru",
        decision_options=(
            DecisionOption(id="rename_ru", label="Переименовать по-русски", effect="Переименовать файл"),
            DecisionOption(id="keep", label="Оставить как есть", effect="Зафиксировать исключение"),
        ),
    )

    result = apply_attention_decision(item, "keep")

    assert result.attention_id == "review-2"
    assert result.selected_option_id == "keep"
    assert result.selected_label == "Оставить как есть"
    assert result.payload.reply_markup is None
    assert "✅ Решение принято: Оставить как есть" in result.payload.text
    assert "кноп" not in result.payload.text.lower()


def test_unknown_attention_decision_is_safe_noop_without_buttons():
    item = AttentionItem(
        attention_id="review-3",
        title="Спорный пункт",
        project="Vault",
        path="C:/vault/file.md",
        reason="Нужно решение",
        risk="Есть риск",
        recommended_option="keep",
        decision_options=(DecisionOption(id="keep", label="Оставить как есть", effect="Ничего не менять"),),
    )

    result = apply_attention_decision(item, "missing")

    assert result.selected_option_id == "missing"
    assert result.applied is False
    assert result.payload.reply_markup is None
    assert "Неизвестный вариант решения" in result.payload.text


def test_recorded_decision_payload_is_idempotent_without_buttons():
    item = AttentionItem(
        attention_id="review-4",
        title="Выбрать действие",
        project="Vault",
        path="C:/vault/file.md",
        reason="Нужно решение",
        risk="Есть риск",
        recommended_option="keep",
        decision_options=(DecisionOption(id="keep", label="Оставить", effect="Не менять"),),
    )
    result = apply_attention_decision(item, "keep")
    record = decision_record_from_result(item, result)

    duplicate_payload = recorded_decision_payload(record, duplicate=True)

    assert duplicate_payload.reply_markup is None
    assert "уже было принято" in duplicate_payload.text
    assert "кноп" not in duplicate_payload.text.lower()
