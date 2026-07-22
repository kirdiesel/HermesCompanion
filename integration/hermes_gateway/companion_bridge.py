"""Optional durable Companion bridge for the installed Hermes Gateway.

This file is the canonical source template for ``gateway/companion_bridge.py``.
Completion feedback remains the primary bridge behavior.  Proactive delivery is
an independently configured, fail-closed extension that is disabled by default
and reuses the Gateway's existing Telegram adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
import math
import os
from pathlib import Path
import re
from typing import Any, Callable, Optional

from hermes_cli.config import get_hermes_home


logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_CHAT_ID = re.compile(r"-?[1-9][0-9]{0,18}\Z")

PROACTIVE_ENABLED_ENV = "HERMES_TG_COMPANION_PROACTIVE_ENABLED"
PROACTIVE_CHAT_ID_ENV = "HERMES_TG_COMPANION_PROACTIVE_CHAT_ID"


def _enabled() -> bool:
    return os.getenv("HERMES_TG_COMPANION_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _proactive_enabled() -> bool:
    return os.getenv(PROACTIVE_ENABLED_ENV, "").strip().lower() in _TRUE_VALUES


@dataclass(frozen=True)
class ProactiveBridgeConfig:
    chat_id: str
    runtime_root: Path
    database_path: Path
    spool_root: Path
    expected_morning_producers: tuple[str, ...] = ("automation", "automation-3")
    poll_interval_seconds: float = 5.0
    morning_barrier_seconds: float = 1500.0
    lease_seconds: float = 60.0
    retry_delay_seconds: float = 60.0
    max_attempts: int = 3
    max_spool_per_cycle: int = 10
    max_batches_per_cycle: int = 10
    max_deliveries_per_cycle: int = 5
    worker_id: str = "hermes-proactive"


class _ProactiveConfigurationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError as error:
        raise _ProactiveConfigurationError(f"invalid_{name.lower()}") from error
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise _ProactiveConfigurationError(f"invalid_{name.lower()}")
    return value


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    stripped = raw.strip()
    if not stripped.isascii() or not stripped.isdecimal():
        raise _ProactiveConfigurationError(f"invalid_{name.lower()}")
    value = int(stripped)
    if not minimum <= value <= maximum:
        raise _ProactiveConfigurationError(f"invalid_{name.lower()}")
    return value


def _load_proactive_config() -> ProactiveBridgeConfig:
    raw_chat_id = os.getenv(PROACTIVE_CHAT_ID_ENV, "").strip()
    if not _CHAT_ID.fullmatch(raw_chat_id):
        raise _ProactiveConfigurationError("invalid_proactive_chat_id")
    chat_number = int(raw_chat_id)
    if not -(2**63) <= chat_number <= 2**63 - 1:
        raise _ProactiveConfigurationError("invalid_proactive_chat_id")

    # These paths are intentionally not configurable from an envelope or an
    # environment variable.  They share the trusted local Companion root used
    # by completion feedback while keeping spool state outside Git and Vault.
    runtime_root = Path(get_hermes_home()) / "tg-companion"
    return ProactiveBridgeConfig(
        chat_id=raw_chat_id,
        runtime_root=runtime_root,
        database_path=runtime_root / "runtime.sqlite3",
        spool_root=runtime_root / "spool",
        poll_interval_seconds=_bounded_float(
            "HERMES_TG_COMPANION_PROACTIVE_POLL_INTERVAL_SECONDS", 5.0, 0.25, 300.0
        ),
        morning_barrier_seconds=_bounded_float(
            "HERMES_TG_COMPANION_PROACTIVE_MORNING_BARRIER_SECONDS", 1500.0, 0.0, 7200.0
        ),
        lease_seconds=_bounded_float(
            "HERMES_TG_COMPANION_PROACTIVE_LEASE_SECONDS", 60.0, 5.0, 3600.0
        ),
        retry_delay_seconds=_bounded_float(
            "HERMES_TG_COMPANION_PROACTIVE_RETRY_DELAY_SECONDS", 60.0, 1.0, 21600.0
        ),
        max_attempts=_bounded_int("HERMES_TG_COMPANION_PROACTIVE_MAX_ATTEMPTS", 3, 1, 20),
        max_spool_per_cycle=_bounded_int(
            "HERMES_TG_COMPANION_PROACTIVE_MAX_SPOOL_PER_CYCLE", 10, 1, 100
        ),
        max_batches_per_cycle=_bounded_int(
            "HERMES_TG_COMPANION_PROACTIVE_MAX_BATCHES_PER_CYCLE", 10, 1, 100
        ),
        max_deliveries_per_cycle=_bounded_int(
            "HERMES_TG_COMPANION_PROACTIVE_MAX_DELIVERIES_PER_CYCLE", 5, 1, 50
        ),
    )


def _build_canonical_proactive_worker(
    *, config: ProactiveBridgeConfig, adapter: Any
) -> Any:
    from tg_companion_bot.delivery_outbox import SpoolLayout, SQLiteDeliveryOutbox
    from tg_companion_bot.hermes_proactive_worker import (
        HermesProactiveWorker,
        HermesProactiveWorkerConfig,
    )

    worker_config = HermesProactiveWorkerConfig(
        chat_id=config.chat_id,
        expected_morning_producers=config.expected_morning_producers,
        poll_interval_seconds=config.poll_interval_seconds,
        morning_barrier_seconds=config.morning_barrier_seconds,
        lease_seconds=config.lease_seconds,
        retry_delay_seconds=config.retry_delay_seconds,
        max_attempts=config.max_attempts,
        max_spool_per_cycle=config.max_spool_per_cycle,
        max_batches_per_cycle=config.max_batches_per_cycle,
        max_deliveries_per_cycle=config.max_deliveries_per_cycle,
        worker_id=config.worker_id,
    )
    layout = SpoolLayout(config.spool_root)
    store = SQLiteDeliveryOutbox(config.database_path)
    return HermesProactiveWorker(
        config=worker_config,
        layout=layout,
        store=store,
        adapter=adapter,
    )


ProactiveWorkerFactory = Callable[..., Any]


class TelegramCompanionBridge:
    def __init__(
        self,
        *,
        proactive_worker_factory: ProactiveWorkerFactory | None = None,
    ) -> None:
        from tg_companion_bot.runtime_state_store import SQLiteRuntimeStateStore

        state_path = get_hermes_home() / "tg-companion" / "runtime.sqlite3"
        self.store = SQLiteRuntimeStateStore(state_path)
        self.store.initialize()
        configured_root = os.getenv("HERMES_TG_COMPANION_OBSIDIAN_ROOT", "").strip()
        self.obsidian_root: Optional[Path] = Path(configured_root) if configured_root else None

        self._proactive_worker_factory = proactive_worker_factory or _build_canonical_proactive_worker
        self._proactive_config: ProactiveBridgeConfig | None = None
        self._proactive_worker: Any | None = None
        self._proactive_started = False
        self._proactive_lock = asyncio.Lock()
        self.proactive_error_code: str | None = None

        if _proactive_enabled():
            try:
                self._proactive_config = _load_proactive_config()
            except _ProactiveConfigurationError as error:
                self.proactive_error_code = error.code
                logger.error("Telegram companion proactive delivery disabled: invalid configuration")

    @property
    def proactive_config(self) -> ProactiveBridgeConfig | None:
        return self._proactive_config

    @property
    def proactive_running(self) -> bool:
        worker_running = getattr(self._proactive_worker, "is_running", self._proactive_started)
        return bool(self._proactive_started and worker_running)

    async def start_proactive(self, adapter: Any) -> bool:
        """Start proactive delivery without affecting completion feedback.

        Configuration and worker failures are contained here so Gateway connect
        remains healthy and completion feedback stays available.
        """

        if self._proactive_config is None:
            return False
        async with self._proactive_lock:
            if self._proactive_started:
                return True
            worker: Any | None = None
            try:
                worker = self._proactive_worker_factory(
                    config=self._proactive_config,
                    adapter=adapter,
                )
                await worker.start()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._proactive_worker = None
                self._proactive_started = False
                self.proactive_error_code = "proactive_start_failed"
                logger.error("Telegram companion proactive delivery failed to start")
                return False
            self._proactive_worker = worker
            self._proactive_started = True
            self.proactive_error_code = None
            logger.info("Telegram companion proactive delivery started")
            return True

    async def stop_proactive(self) -> bool:
        """Stop the optional worker; a stop failure is isolated from Gateway."""

        async with self._proactive_lock:
            worker = self._proactive_worker
            if worker is None:
                self._proactive_started = False
                return False
            self._proactive_worker = None
            self._proactive_started = False
            try:
                await worker.stop()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.proactive_error_code = "proactive_stop_failed"
                logger.error("Telegram companion proactive delivery failed to stop")
                return False
            logger.info("Telegram companion proactive delivery stopped")
            return True

    def apply_feedback(self, query: Any, action: str, state: dict[str, Any]) -> Any:
        from tg_companion_bot.hermes_gateway_adapter import apply_persisted_completion_feedback

        message = getattr(query, "message", None)
        if message is None:
            raise ValueError("Completion feedback callback has no Telegram message")
        text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        if not str(text).strip():
            raise ValueError("Completion feedback callback has no result text")
        metadata = state.get("metadata") if isinstance(state, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        project = str(metadata.get("companion_project") or "Inbox")
        return apply_persisted_completion_feedback(
            action=action,
            chat_id=str(getattr(message, "chat_id", "")),
            message_id=str(getattr(message, "message_id", "")),
            result_text=str(text),
            store=self.store,
            project=project,
            obsidian_root=self.obsidian_root,
        )


def build_telegram_companion_bridge(
    *, proactive_worker_factory: ProactiveWorkerFactory | None = None
) -> Optional[TelegramCompanionBridge]:
    if not _enabled():
        return None
    try:
        bridge = TelegramCompanionBridge(proactive_worker_factory=proactive_worker_factory)
    except Exception as error:
        logger.exception("Telegram companion bridge disabled after initialization failure: %s", error)
        return None
    logger.info("Telegram companion bridge enabled (real Vault writes: %s)", bool(bridge.obsidian_root))
    return bridge
