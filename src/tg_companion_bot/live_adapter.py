from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AdapterConfig:
    bot_token: str | None
    obsidian_vault: Path
    default_project: str

    @property
    def has_bot_token(self) -> bool:
        return bool(self.bot_token)

    @property
    def bot_token_preview(self) -> str:
        if not self.bot_token:
            return "<missing>"
        if ":" in self.bot_token:
            prefix = self.bot_token.split(":", 1)[0]
            return f"{prefix}:***"
        return "***"


@dataclass(frozen=True)
class LiveRunPlan:
    mode: str
    ready: bool
    can_consume_updates: bool
    can_send_messages: bool
    needs_confirmation: bool
    checks: tuple[str, ...]
    risks: tuple[str, ...]
    blockers: tuple[str, ...]


def load_adapter_config(env_file: Path) -> AdapterConfig:
    values = _parse_env_file(env_file)
    return AdapterConfig(
        bot_token=values.get("BOT_TOKEN") or None,
        obsidian_vault=Path(values.get("OBSIDIAN_VAULT") or "C:/AIProjects/Obsidian/One"),
        default_project=values.get("DEFAULT_PROJECT") or "TG Bot Companion",
    )


def build_live_run_plan(config: AdapterConfig) -> LiveRunPlan:
    blockers: list[str] = []
    if not config.has_bot_token:
        blockers.append("BOT_TOKEN is missing")
    if not str(config.obsidian_vault):
        blockers.append("OBSIDIAN_VAULT is missing")

    return LiveRunPlan(
        mode="dry-run",
        ready=not blockers,
        can_consume_updates=False,
        can_send_messages=False,
        needs_confirmation=True,
        checks=(
            "BotFather token",
            "Obsidian vault path",
            "Default project",
            "Core renderer/callback/persistence tests",
        ),
        risks=(
            "polling conflict",
            "accidental message sending before UX acceptance",
            "token leakage in logs or reports",
        ),
        blockers=tuple(blockers),
    )


def _parse_env_file(env_file: Path) -> dict[str, str]:
    if not env_file.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _strip_quotes(value.strip())
    return values


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
