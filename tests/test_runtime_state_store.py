from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tg_companion_bot.attention_items import (
    AttentionDecisionRecord,
    AttentionItem,
    DecisionOption,
)
from tg_companion_bot.hermes_gateway_adapter import (
    HermesInboundEvent,
    apply_persisted_completion_feedback,
    plan_persisted_attention_item,
    plan_persisted_hermes_event,
)
from tg_companion_bot.live_runtime import (
    CompanionDecisionRecord,
    PendingResult,
    RuntimeState,
)
from tg_companion_bot.runtime_state_store import SQLiteRuntimeStateStore
from tg_companion_bot.state_codec import runtime_state_from_dict, runtime_state_to_dict


def attention_item() -> AttentionItem:
    return AttentionItem(
        attention_id="review-1",
        title="Решить судьбу файла",
        project="Obsidian",
        path="C:/Vault/file.md",
        reason="Требуется решение",
        risk="Можно потерять контекст",
        recommended_option="archive",
        decision_options=(
            DecisionOption(id="archive", label="Архивировать", effect="Перенести в архив"),
            DecisionOption(id="keep", label="Оставить", effect="Ничего не менять"),
        ),
    )


def test_state_codec_round_trips_all_runtime_state_sections(tmp_path: Path) -> None:
    state = RuntimeState(obsidian_root=tmp_path / "vault")
    state.pending_results["101"] = PendingResult(
        chat_id="777",
        message_id="101",
        summary="Pending summary",
    )
    state.companion_decisions["resolved-result"] = CompanionDecisionRecord(
        task_id="resolved-result",
        action="accept",
        status="✅ готово",
        follow_up="Продолжить",
    )
    state.pending_attention_items["review-1"] = attention_item()
    state.attention_decisions["resolved-1"] = AttentionDecisionRecord(
        attention_id="resolved-1",
        option_id="keep",
        selected_label="Оставить",
        effect="Ничего не менять",
        title="Решённый пункт",
    )

    restored = runtime_state_from_dict(
        runtime_state_to_dict(state),
        obsidian_root=state.obsidian_root,
    )

    assert restored == state


def test_sqlite_store_survives_restart_and_skips_noop_revision(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = SQLiteRuntimeStateStore(path)

    with store.transaction() as state:
        state.pending_results["101"] = PendingResult("777", "101", "Pending")

    assert store.revision() == 1
    restarted = SQLiteRuntimeStateStore(path)
    assert restarted.load().pending_results["101"].summary == "Pending"

    with restarted.transaction():
        pass

    assert restarted.revision() == 1


def test_sqlite_transaction_rolls_back_state_change_on_error(tmp_path: Path) -> None:
    store = SQLiteRuntimeStateStore(tmp_path / "runtime.sqlite3")

    with pytest.raises(ValueError, match="abort"):
        with store.transaction() as state:
            state.pending_results["101"] = PendingResult("777", "101", "Pending")
            raise ValueError("abort")

    assert store.revision() == 0
    assert store.load().pending_results == {}


def test_persisted_hermes_flow_survives_store_restart_and_writes_temp_vault(tmp_path: Path) -> None:
    store_path = tmp_path / "runtime.sqlite3"
    vault_root = tmp_path / "vault"
    message = HermesInboundEvent(
        kind="message",
        chat_id="777",
        user_id="42",
        message_id="101",
        text="Итог для безопасной записи",
    )

    message_plan = plan_persisted_hermes_event(
        message,
        store=SQLiteRuntimeStateStore(store_path),
        allowed_chat_id="777",
        allowed_user_id="42",
    )

    assert message_plan.ok is True
    restarted = SQLiteRuntimeStateStore(store_path)
    assert restarted.load().pending_results["101"].summary == "Итог для безопасной записи"

    callback = HermesInboundEvent(
        kind="callback",
        chat_id="777",
        user_id="42",
        message_id="101",
        callback_data="companion:accept:101",
    )
    callback_plan = plan_persisted_hermes_event(
        callback,
        store=restarted,
        allowed_chat_id="777",
        allowed_user_id="42",
        obsidian_root=vault_root,
    )

    assert callback_plan.ok is True
    assert [action.kind for action in callback_plan.actions] == ["answer_callback", "edit_message"]
    assert restarted.load().pending_results == {}
    decision_note = (
        vault_root
        / "03_Проекты"
        / "Активные"
        / "Inbox"
        / "_tg-companion"
        / "Решения"
        / "101.md"
    )
    assert decision_note.exists()


def test_concurrent_attention_callbacks_apply_once_and_persist_duplicate(tmp_path: Path) -> None:
    store = SQLiteRuntimeStateStore(tmp_path / "runtime.sqlite3")
    created = plan_persisted_attention_item(attention_item(), chat_id="777", store=store)
    assert created.ok is True

    callback = HermesInboundEvent(
        kind="callback",
        chat_id="777",
        user_id="42",
        message_id="900",
        callback_data="attention:review-1:archive",
    )

    def apply_callback(_: int) -> str:
        plan = plan_persisted_hermes_event(
            callback,
            store=store,
            allowed_chat_id="777",
            allowed_user_id="42",
        )
        assert plan.ok is True
        edit = next(action for action in plan.actions if action.kind == "edit_message")
        return str(edit.metadata["attention_status"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(apply_callback, range(2)))

    assert statuses == ["applied", "duplicate"]
    restored = store.load()
    assert restored.pending_attention_items == {}
    assert restored.attention_decisions["review-1"].option_id == "archive"


def test_unauthorized_persisted_event_does_not_create_state_revision(tmp_path: Path) -> None:
    store = SQLiteRuntimeStateStore(tmp_path / "runtime.sqlite3")
    event = HermesInboundEvent(
        kind="message",
        chat_id="other",
        user_id="42",
        message_id="101",
        text="Unauthorized",
    )

    plan = plan_persisted_hermes_event(
        event,
        store=store,
        allowed_chat_id="777",
        allowed_user_id="42",
    )

    assert plan.ok is False
    assert plan.error == "unauthorized_source"
    assert store.revision() == 0


def test_existing_hermes_feedback_survives_restart_without_obsidian_write(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "runtime.sqlite3"
    store = SQLiteRuntimeStateStore(store_path)

    first_process = apply_persisted_completion_feedback(
        action="accept",
        chat_id="777",
        message_id="smoke-101",
        result_text="Проверка durable callback после перезапуска Gateway",
        store=store,
        project="Smoke",
        obsidian_root=None,
    )

    restarted = SQLiteRuntimeStateStore(store_path)
    duplicate_after_restart = apply_persisted_completion_feedback(
        action="accept",
        chat_id="777",
        message_id="smoke-101",
        result_text="Проверка durable callback после перезапуска Gateway",
        store=restarted,
        project="Smoke",
        obsidian_root=None,
    )

    state = restarted.load()
    assert first_process.applied is True
    assert duplicate_after_restart.applied is False
    assert duplicate_after_restart.duplicate is True
    assert state.pending_results == {}
    assert state.companion_decisions["telegram-777-smoke-101"].action == "accept"
    assert not (tmp_path / "vault").exists()


def test_existing_hermes_feedback_is_idempotent_and_rejects_conflicting_action(
    tmp_path: Path,
) -> None:
    store = SQLiteRuntimeStateStore(tmp_path / "runtime.sqlite3")
    vault_root = tmp_path / "vault"
    arguments = {
        "chat_id": "777",
        "message_id": "101",
        "result_text": "Финальный ответ Hermes",
        "store": store,
        "project": "Hermes",
        "obsidian_root": vault_root,
    }

    first = apply_persisted_completion_feedback(action="accept", **arguments)
    duplicate = apply_persisted_completion_feedback(action="accept", **arguments)
    conflict = apply_persisted_completion_feedback(action="revise", **arguments)

    assert first.applied is True
    assert first.duplicate is False
    assert duplicate.applied is False
    assert duplicate.duplicate is True
    assert duplicate.error is None
    assert conflict.applied is False
    assert conflict.duplicate is False
    assert conflict.error == "companion_result_already_resolved"

    state = store.load()
    assert state.pending_results == {}
    assert state.companion_decisions["telegram-777-101"].action == "accept"
    journal = (
        vault_root
        / "03_Проекты"
        / "Активные"
        / "Hermes"
        / "_tg-companion"
        / "Журнал решений.md"
    ).read_text(encoding="utf-8")
    assert journal.count("tg-companion:journal:telegram-777-101") == 1
