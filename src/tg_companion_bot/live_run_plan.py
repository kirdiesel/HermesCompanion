from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class FrameworkChoice:
    name: str
    major_version: int
    rationale: str
    supports: List[str]
    does_not_start_polling: bool


@dataclass(frozen=True)
class LiveRunSafetyPlan:
    framework: FrameworkChoice
    mode: str
    requires_user_confirmation: bool
    requires_botfather_token: bool
    consumes_updates: bool
    sends_messages: bool
    allowed_without_confirmation: List[str]
    activation_gates: List[str]
    risks: List[str]


def choose_framework() -> FrameworkChoice:
    return FrameworkChoice(
        name="aiogram",
        major_version=3,
        rationale=(
            "aiogram 3 is a good fit for an async Telegram bot adapter: "
            "handlers can stay thin while the reusable core remains framework-neutral."
        ),
        supports=[
            "async handlers",
            "inline keyboards",
            "callback queries",
            "polling",
            "webhooks",
        ],
        does_not_start_polling=True,
    )


def build_live_run_safety_plan(framework: FrameworkChoice) -> LiveRunSafetyPlan:
    return LiveRunSafetyPlan(
        framework=framework,
        mode="dry_run",
        requires_user_confirmation=True,
        requires_botfather_token=True,
        consumes_updates=False,
        sends_messages=False,
        allowed_without_confirmation=[
            "render_payload",
            "parse_update_fixture",
            "run_smoke_cli",
            "validate_config_without_token",
        ],
        activation_gates=[
            "all_tests_green",
            "explicit_user_confirmation",
            "botfather_token_configured_outside_git",
            "no_existing_polling_conflict",
            "dry_run_payload_verified",
            "single_chat_limited_smoke",
        ],
        risks=[
            "token leakage",
            "polling conflict",
            "accidental sends",
            "wrong chat targeting",
        ],
    )
