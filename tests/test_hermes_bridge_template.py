from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import uuid

import pytest


TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "integration"
    / "hermes_gateway"
    / "companion_bridge.py"
)

PROACTIVE_ENV = (
    "HERMES_TG_COMPANION_PROACTIVE_ENABLED",
    "HERMES_TG_COMPANION_PROACTIVE_CHAT_ID",
    "HERMES_TG_COMPANION_PROACTIVE_POLL_INTERVAL_SECONDS",
    "HERMES_TG_COMPANION_PROACTIVE_MORNING_BARRIER_SECONDS",
    "HERMES_TG_COMPANION_PROACTIVE_LEASE_SECONDS",
    "HERMES_TG_COMPANION_PROACTIVE_RETRY_DELAY_SECONDS",
    "HERMES_TG_COMPANION_PROACTIVE_MAX_ATTEMPTS",
    "HERMES_TG_COMPANION_PROACTIVE_MAX_SPOOL_PER_CYCLE",
    "HERMES_TG_COMPANION_PROACTIVE_MAX_BATCHES_PER_CYCLE",
    "HERMES_TG_COMPANION_PROACTIVE_MAX_DELIVERIES_PER_CYCLE",
)


def _load_template(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in (
        "HERMES_TG_COMPANION_ENABLED",
        "HERMES_TG_COMPANION_OBSIDIAN_ROOT",
        *PROACTIVE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    hermes_package = ModuleType("hermes_cli")
    hermes_config = ModuleType("hermes_cli.config")
    hermes_config.get_hermes_home = lambda: tmp_path  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_package)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_config)

    stores: list[object] = []

    class StubRuntimeStateStore:
        def __init__(self, path):
            self.path = Path(path)
            self.initialized = False
            stores.append(self)

        def initialize(self):
            self.initialized = True

    runtime_store = ModuleType("tg_companion_bot.runtime_state_store")
    runtime_store.SQLiteRuntimeStateStore = StubRuntimeStateStore  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tg_companion_bot.runtime_state_store", runtime_store)

    feedback_calls: list[dict] = []

    def apply_feedback_stub(**kwargs):
        feedback_calls.append(kwargs)
        return {"status": "recorded", "action": kwargs["action"]}

    gateway_adapter = ModuleType("tg_companion_bot.hermes_gateway_adapter")
    gateway_adapter.apply_persisted_completion_feedback = apply_feedback_stub  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tg_companion_bot.hermes_gateway_adapter", gateway_adapter)

    module_name = f"_companion_bridge_template_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, TEMPLATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module, stores, feedback_calls


def _enable_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_TG_COMPANION_ENABLED", "true")


def _query(*, text: str = "Готовый результат", caption: str | None = None):
    return SimpleNamespace(
        message=SimpleNamespace(
            text=text,
            caption=caption,
            chat_id=-100123,
            message_id=456,
        )
    )


def test_existing_feedback_flag_keeps_builder_disabled(monkeypatch, tmp_path):
    module, stores, _ = _load_template(monkeypatch, tmp_path)

    assert module._enabled() is False
    assert module.build_telegram_companion_bridge() is None
    assert stores == []


def test_proactive_default_off_is_strict_noop_and_does_not_validate_settings(monkeypatch, tmp_path):
    module, stores, _ = _load_template(monkeypatch, tmp_path)
    _enable_feedback(monkeypatch)
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_CHAT_ID", "not-a-number")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_MAX_ATTEMPTS", "not-a-number")
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        raise AssertionError("default-off bridge must not construct a worker")

    bridge = module.build_telegram_companion_bridge(proactive_worker_factory=factory)

    assert bridge is not None
    assert bridge.proactive_config is None
    assert bridge.proactive_error_code is None
    assert asyncio.run(bridge.start_proactive(object())) is False
    assert asyncio.run(bridge.stop_proactive()) is False
    assert factory_calls == []
    assert len(stores) == 1
    assert stores[0].initialized is True
    assert stores[0].path == tmp_path / "tg-companion" / "runtime.sqlite3"


@pytest.mark.parametrize(
    ("name", "value", "expected_code"),
    [
        ("HERMES_TG_COMPANION_PROACTIVE_CHAT_ID", "chat-123", "invalid_proactive_chat_id"),
        (
            "HERMES_TG_COMPANION_PROACTIVE_POLL_INTERVAL_SECONDS",
            "0",
            "invalid_hermes_tg_companion_proactive_poll_interval_seconds",
        ),
        (
            "HERMES_TG_COMPANION_PROACTIVE_MAX_DELIVERIES_PER_CYCLE",
            "9999",
            "invalid_hermes_tg_companion_proactive_max_deliveries_per_cycle",
        ),
    ],
)
def test_invalid_enabled_config_fails_closed_for_proactive_only(
    monkeypatch, tmp_path, name, value, expected_code
):
    module, _, feedback_calls = _load_template(monkeypatch, tmp_path)
    _enable_feedback(monkeypatch)
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_ENABLED", "yes")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_CHAT_ID", "-100123")
    monkeypatch.setenv(name, value)

    bridge = module.build_telegram_companion_bridge(
        proactive_worker_factory=lambda **_: pytest.fail("invalid config constructed worker")
    )

    assert bridge is not None
    assert bridge.proactive_config is None
    assert bridge.proactive_error_code == expected_code
    assert asyncio.run(bridge.start_proactive(object())) is False

    result = bridge.apply_feedback(
        _query(),
        "accept",
        {"metadata": {"companion_project": "Project Alpha"}},
    )
    assert result == {"status": "recorded", "action": "accept"}
    assert feedback_calls[0]["project"] == "Project Alpha"


def test_valid_config_uses_fixed_roots_and_starts_and_stops_injected_worker(monkeypatch, tmp_path):
    module, _, _ = _load_template(monkeypatch, tmp_path)
    _enable_feedback(monkeypatch)
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_ENABLED", "1")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_POLL_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_MORNING_BARRIER_SECONDS", "900")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_MAX_DELIVERIES_PER_CYCLE", "2")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_SPOOL_ROOT", "C:/untrusted/override")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_DATABASE_PATH", "C:/untrusted/db.sqlite3")

    class StubWorker:
        def __init__(self):
            self.starts = 0
            self.stops = 0
            self.is_running = False

        async def start(self):
            self.starts += 1
            self.is_running = True

        async def stop(self):
            self.stops += 1
            self.is_running = False

    worker = StubWorker()
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return worker

    bridge = module.build_telegram_companion_bridge(proactive_worker_factory=factory)
    assert bridge is not None
    config = bridge.proactive_config
    assert config is not None
    assert config.chat_id == "-1001234567890"
    assert config.runtime_root == tmp_path / "tg-companion"
    assert config.database_path == tmp_path / "tg-companion" / "runtime.sqlite3"
    assert config.spool_root == tmp_path / "tg-companion" / "spool"
    assert config.poll_interval_seconds == 2.5
    assert config.morning_barrier_seconds == 900.0
    assert config.max_attempts == 4
    assert config.max_deliveries_per_cycle == 2
    assert config.expected_morning_producers == ("automation", "automation-3")

    adapter = object()

    async def lifecycle():
        assert await bridge.start_proactive(adapter) is True
        assert await bridge.start_proactive(adapter) is True
        assert bridge.proactive_running is True
        assert await bridge.stop_proactive() is True
        assert await bridge.stop_proactive() is False

    asyncio.run(lifecycle())

    assert len(factory_calls) == 1
    assert factory_calls[0] == {"config": config, "adapter": adapter}
    assert worker.starts == 1
    assert worker.stops == 1
    assert bridge.proactive_running is False


def test_worker_start_failure_does_not_disable_completion_feedback(monkeypatch, tmp_path):
    module, _, feedback_calls = _load_template(monkeypatch, tmp_path)
    _enable_feedback(monkeypatch)
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("HERMES_TG_COMPANION_PROACTIVE_CHAT_ID", "123456")

    class FailingWorker:
        async def start(self):
            raise RuntimeError("stub start failure")

        async def stop(self):
            raise AssertionError("failed worker must not be retained")

    bridge = module.build_telegram_companion_bridge(
        proactive_worker_factory=lambda **_: FailingWorker()
    )
    assert bridge is not None

    assert asyncio.run(bridge.start_proactive(object())) is False
    assert bridge.proactive_error_code == "proactive_start_failed"
    assert bridge.proactive_running is False
    assert asyncio.run(bridge.stop_proactive()) is False

    bridge.apply_feedback(_query(), "revise", {"metadata": {}})
    assert feedback_calls[0]["action"] == "revise"
    assert feedback_calls[0]["project"] == "Inbox"


def test_apply_feedback_semantics_and_real_vault_default_off_are_unchanged(monkeypatch, tmp_path):
    module, stores, feedback_calls = _load_template(monkeypatch, tmp_path)
    _enable_feedback(monkeypatch)

    bridge = module.build_telegram_companion_bridge()
    assert bridge is not None
    assert bridge.obsidian_root is None

    result = bridge.apply_feedback(
        _query(text="Проверенный итог"),
        "next",
        {"metadata": {"companion_project": "Roadmap"}},
    )

    assert result == {"status": "recorded", "action": "next"}
    assert feedback_calls == [
        {
            "action": "next",
            "chat_id": "-100123",
            "message_id": "456",
            "result_text": "Проверенный итог",
            "store": stores[0],
            "project": "Roadmap",
            "obsidian_root": None,
        }
    ]


def test_apply_feedback_still_rejects_missing_message_or_result(monkeypatch, tmp_path):
    module, _, _ = _load_template(monkeypatch, tmp_path)
    _enable_feedback(monkeypatch)
    bridge = module.build_telegram_companion_bridge()
    assert bridge is not None

    with pytest.raises(ValueError, match="no Telegram message"):
        bridge.apply_feedback(SimpleNamespace(message=None), "accept", {})
    with pytest.raises(ValueError, match="no result text"):
        bridge.apply_feedback(_query(text="", caption=""), "accept", {})

