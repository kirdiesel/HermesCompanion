from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .attention_items import AttentionDecisionRecord, AttentionItem, DecisionOption
from .live_runtime import CompanionDecisionRecord, PendingResult, RuntimeState


STATE_SCHEMA_VERSION = 1


class StateCodecError(ValueError):
    """Raised when persisted runtime state does not match the expected schema."""


def runtime_state_to_dict(state: RuntimeState) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "pending_results": {
            result_id: asdict(pending)
            for result_id, pending in sorted(state.pending_results.items())
        },
        "companion_decisions": {
            task_id: asdict(record)
            for task_id, record in sorted(state.companion_decisions.items())
        },
        "pending_attention_items": {
            attention_id: asdict(item)
            for attention_id, item in sorted(state.pending_attention_items.items())
        },
        "attention_decisions": {
            attention_id: asdict(record)
            for attention_id, record in sorted(state.attention_decisions.items())
        },
    }


def runtime_state_from_dict(
    data: Mapping[str, Any],
    *,
    obsidian_root: Path | str | None = None,
) -> RuntimeState:
    if not isinstance(data, Mapping):
        raise StateCodecError("state JSON must be an object")

    version = data.get("schema_version", STATE_SCHEMA_VERSION)
    if version != STATE_SCHEMA_VERSION:
        raise StateCodecError(f"unsupported state schema version: {version!r}")

    state = RuntimeState(
        obsidian_root=Path(obsidian_root) if obsidian_root is not None else None
    )
    _load_pending_results(data, state)
    _load_companion_decisions(data, state)
    _load_attention_items(data, state)
    _load_attention_decisions(data, state)
    return state


def attention_item_from_dict(data: Mapping[str, Any]) -> AttentionItem:
    try:
        raw_options = data.get("decision_options", [])
        if not isinstance(raw_options, (list, tuple)):
            raise StateCodecError("attention decision_options must be an array")
        options = tuple(
            DecisionOption(
                id=str(option["id"]),
                label=str(option["label"]),
                effect=str(option.get("effect", "")),
            )
            for option in raw_options
            if isinstance(option, Mapping)
        )
        return AttentionItem(
            attention_id=str(data["attention_id"]),
            title=str(data["title"]),
            project=str(data.get("project", "")),
            path=str(data.get("path", "")),
            reason=str(data.get("reason", "")),
            risk=str(data.get("risk", "")),
            recommended_option=str(
                data.get("recommended_option") or (options[0].id if options else "")
            ),
            decision_options=options,
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, StateCodecError):
            raise
        raise StateCodecError(f"invalid attention item: {error}") from error


def _state_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, Mapping):
        raise StateCodecError(f"state.{key} must be an object")
    return value


def _load_pending_results(data: Mapping[str, Any], state: RuntimeState) -> None:
    for key, value in _state_mapping(data, "pending_results").items():
        if not isinstance(value, Mapping):
            raise StateCodecError("pending result must be an object")
        summary = value.get("summary")
        if not isinstance(summary, str):
            raise StateCodecError("pending result summary must be a string")
        message_id = str(value.get("message_id") or key)
        state.pending_results[message_id] = PendingResult(
            chat_id=str(value.get("chat_id") or ""),
            message_id=message_id,
            summary=summary,
        )


def _load_attention_items(data: Mapping[str, Any], state: RuntimeState) -> None:
    for attention_id, value in _state_mapping(data, "pending_attention_items").items():
        if not isinstance(value, Mapping):
            raise StateCodecError("pending attention item must be an object")
        item = attention_item_from_dict(value)
        if item.attention_id != str(attention_id):
            raise StateCodecError("pending attention item id does not match state key")
        state.pending_attention_items[item.attention_id] = item


def _load_companion_decisions(data: Mapping[str, Any], state: RuntimeState) -> None:
    for task_id, value in _state_mapping(data, "companion_decisions").items():
        if not isinstance(value, Mapping):
            raise StateCodecError("companion decision must be an object")
        try:
            record = CompanionDecisionRecord(
                task_id=str(value.get("task_id") or task_id),
                action=str(value["action"]),
                status=str(value.get("status", "")),
                follow_up=str(value.get("follow_up", "")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise StateCodecError(f"invalid companion decision: {error}") from error
        if record.task_id != str(task_id):
            raise StateCodecError("companion decision id does not match state key")
        state.companion_decisions[record.task_id] = record


def _load_attention_decisions(data: Mapping[str, Any], state: RuntimeState) -> None:
    for attention_id, value in _state_mapping(data, "attention_decisions").items():
        if not isinstance(value, Mapping):
            raise StateCodecError("attention decision must be an object")
        try:
            record = AttentionDecisionRecord(
                attention_id=str(value.get("attention_id") or attention_id),
                option_id=str(value["option_id"]),
                selected_label=str(value["selected_label"]),
                effect=str(value.get("effect", "")),
                title=str(value.get("title", "")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise StateCodecError(f"invalid attention decision: {error}") from error
        if record.attention_id != str(attention_id):
            raise StateCodecError("attention decision id does not match state key")
        state.attention_decisions[record.attention_id] = record
