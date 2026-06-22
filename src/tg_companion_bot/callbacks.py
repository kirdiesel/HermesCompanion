from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

DONE_STATUS = "✅ готово"
IN_PROGRESS_STATUS = "▶️ выполняется"
REVIEW_STATUS = "🔎 приёмка"


class CallbackAction(str, Enum):
    ACCEPT = "accept"
    REVISE = "revise"
    NEXT = "next"


@dataclass(frozen=True)
class CallbackDecision:
    action: CallbackAction
    task_id: str


@dataclass(frozen=True)
class CallbackResult:
    task_id: str | None
    status: str | None
    remove_keyboard: bool
    next_intent: str
    user_message: str


def parse_callback_data(data: str) -> CallbackDecision | None:
    """Parse framework-agnostic callback data.

    Format: companion:<action>:<task_id>
    Kept intentionally small so it can be reused by different Telegram adapters.
    """
    if not data:
        return None

    parts = data.split(":", 2)
    if len(parts) != 3:
        return None

    namespace, action_raw, task_id = parts
    if namespace != "companion" or not task_id:
        return None

    try:
        action = CallbackAction(action_raw)
    except ValueError:
        return None

    return CallbackDecision(action=action, task_id=task_id)


def handle_callback(data: str, *, has_recommendation: bool = False) -> CallbackResult:
    decision = parse_callback_data(data)
    if decision is None:
        return CallbackResult(
            task_id=None,
            status=None,
            remove_keyboard=False,
            next_intent="noop",
            user_message="Не поняла это действие. Лучше продолжу без изменения статуса.",
        )

    if decision.action is CallbackAction.ACCEPT:
        next_intent = "run_recommendation" if has_recommendation else "run_optimal_next_step"
        return CallbackResult(
            task_id=decision.task_id,
            status=DONE_STATUS,
            remove_keyboard=True,
            next_intent=next_intent,
            user_message="✅ Результат принят. Перехожу к рекомендации; если её нет — к следующему оптимальному шагу.",
        )

    if decision.action is CallbackAction.REVISE:
        return CallbackResult(
            task_id=decision.task_id,
            status=IN_PROGRESS_STATUS,
            remove_keyboard=True,
            next_intent="await_revision_instructions",
            user_message="🔎 Приняла: нужна доработка. Напиши, что именно поправить, или пришли уточнение.",
        )

    if decision.action is CallbackAction.NEXT:
        return CallbackResult(
            task_id=decision.task_id,
            status=REVIEW_STATUS,
            remove_keyboard=False,
            next_intent="show_next_step",
            user_message="➡️ Показываю следующий оптимальный шаг по текущей задаче.",
        )

    return CallbackResult(
        task_id=decision.task_id,
        status=None,
        remove_keyboard=False,
        next_intent="noop",
        user_message="Не поняла это действие. Лучше продолжу без изменения статуса.",
    )
