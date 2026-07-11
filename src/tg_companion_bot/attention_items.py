from __future__ import annotations

from dataclasses import dataclass


CALLBACK_PREFIX = "attention"
MAX_CALLBACK_DATA_BYTES = 64


@dataclass(frozen=True)
class DecisionOption:
    id: str
    label: str
    effect: str


@dataclass(frozen=True)
class AttentionItem:
    attention_id: str
    title: str
    project: str
    path: str
    reason: str
    risk: str
    recommended_option: str
    decision_options: tuple[DecisionOption, ...]


@dataclass(frozen=True)
class AttentionPayload:
    text: str
    reply_markup: dict | None = None


@dataclass(frozen=True)
class AttentionDecisionResult:
    attention_id: str
    selected_option_id: str
    selected_label: str | None
    applied: bool
    payload: AttentionPayload


@dataclass(frozen=True)
class AttentionCallback:
    attention_id: str
    option_id: str


@dataclass(frozen=True)
class AttentionDecisionRecord:
    attention_id: str
    option_id: str
    selected_label: str
    effect: str
    title: str


def build_attention_callback_data(attention_id: str, option_id: str) -> str:
    callback_data = f"{CALLBACK_PREFIX}:{attention_id}:{option_id}"
    if len(callback_data.encode("utf-8")) > MAX_CALLBACK_DATA_BYTES:
        raise ValueError("Telegram callback data must fit into 64 bytes")
    return callback_data


def parse_attention_callback_data(data: str) -> AttentionCallback | None:
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None
    namespace, attention_id, option_id = parts
    if namespace != CALLBACK_PREFIX or not attention_id or not option_id:
        return None
    return AttentionCallback(attention_id=attention_id, option_id=option_id)


def decision_record_from_result(item: AttentionItem, result: AttentionDecisionResult) -> AttentionDecisionRecord:
    selected = next(option for option in item.decision_options if option.id == result.selected_option_id)
    return AttentionDecisionRecord(
        attention_id=item.attention_id,
        option_id=selected.id,
        selected_label=selected.label,
        effect=selected.effect,
        title=item.title,
    )


def recorded_decision_payload(record: AttentionDecisionRecord, *, duplicate: bool) -> AttentionPayload:
    prefix = "ℹ️ Решение уже было принято" if duplicate else "✅ Решение принято"
    return AttentionPayload(
        text=(
            f"{prefix}: {record.selected_label}\n"
            f"Пункт: {record.title}\n"
            f"Действие: {record.effect}"
        ),
        reply_markup=None,
    )


def attention_item_to_telegram_payload(item: AttentionItem) -> AttentionPayload:
    lines = [
        f"🔴 Требует внимания: {item.title}",
        f"Проект: {item.project}",
    ]
    if item.path:
        lines.append(f"Путь: {item.path}")
    lines.extend([
        f"Причина: {item.reason}",
        f"Риск: {item.risk}",
    ])
    recommended = next(
        (option.label for option in item.decision_options if option.id == item.recommended_option),
        None,
    )
    if recommended:
        lines.append(f"Рекомендация: {recommended}")
    keyboard = []
    for option in item.decision_options:
        keyboard.append([
            {
                "text": option.label,
                "callback_data": build_attention_callback_data(item.attention_id, option.id),
            }
        ])
    return AttentionPayload(
        text="\n".join(lines),
        reply_markup={"inline_keyboard": keyboard},
    )


def apply_attention_decision(item: AttentionItem, option_id: str) -> AttentionDecisionResult:
    selected = next((option for option in item.decision_options if option.id == option_id), None)
    if selected is None:
        return AttentionDecisionResult(
            attention_id=item.attention_id,
            selected_option_id=option_id,
            selected_label=None,
            applied=False,
            payload=AttentionPayload(
                text=(
                    f"⚠️ Неизвестный вариант решения для: {item.title}\n"
                    "Запроси актуальный пункт или пришли решение текстом."
                ),
                reply_markup=None,
            ),
        )

    return AttentionDecisionResult(
        attention_id=item.attention_id,
        selected_option_id=option_id,
        selected_label=selected.label,
        applied=True,
        payload=AttentionPayload(
            text=(
                f"✅ Решение принято: {selected.label}\n"
                f"Пункт: {item.title}\n"
                f"Действие: {selected.effect}"
            ),
            reply_markup=None,
        ),
    )
