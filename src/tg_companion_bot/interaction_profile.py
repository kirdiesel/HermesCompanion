from __future__ import annotations

import sys
from dataclasses import dataclass


SUPPORTED_ACTIONS = ("accept", "revise", "next")


@dataclass(frozen=True)
class ActionLabel:
    action: str
    text: str

    def __post_init__(self) -> None:
        if self.action not in SUPPORTED_ACTIONS:
            raise ValueError(f"Unsupported interaction action: {self.action}")
        if not self.text.strip():
            raise ValueError("Interaction action label must not be empty")


@dataclass(frozen=True)
class InteractionProfile:
    name: str
    in_progress_status: str
    review_status: str
    done_status: str
    actions: tuple[ActionLabel, ...]
    require_explicit_acceptance: bool = True
    persist_only_accepted_results: bool = True
    max_clarifying_questions: int = 1

    def label_for(self, action: str) -> str:
        for item in self.actions:
            if item.action == action:
                return item.text
        raise ValueError(f"Action {action!r} is not configured in profile {self.name!r}")

    @property
    def review_actions(self) -> tuple[str, ...]:
        return tuple(item.action for item in self.actions)


DEFAULT_INTERACTION_PROFILE = InteractionProfile(
    name="Hermes Companion",
    in_progress_status="▶️ выполняется",
    review_status="🔎 приёмка",
    done_status="✅ готово",
    actions=(
        ActionLabel("accept", "Принять результат"),
        ActionLabel("revise", "Доработать результат"),
        ActionLabel("next", "Показать следующий шаг"),
    ),
)


def build_handoff_prompt(profile: InteractionProfile = DEFAULT_INTERACTION_PROFILE) -> str:
    """Return one self-contained prompt for recreating this interaction model."""

    action_lines = "\n".join(
        f"- `{item.text}` -> `{item.action}`" for item in profile.actions
    )
    return (
        "Создай для пользователя Hermes One Telegram-интерфейс общения с агентом.\n\n"
        "Обязательный цикл: задача -> результат -> приёмка -> Obsidian -> следующий шаг.\n\n"
        "Правила интерфейса:\n"
        f"- Пользовательские статусы только: `{profile.in_progress_status}`, "
        f"`{profile.review_status}`, `{profile.done_status}`.\n"
        "- Кнопки показывай только под итоговым результатом или реальным выбором; "
        "не показывай их под прогрессом, справкой, системным сообщением или ошибкой.\n"
        "- Используй минимально достаточное число доступных действий. Базовые действия:\n"
        f"{action_lines}\n"
        "- Результат считается готовым только после явного `accept`.\n"
        "- `revise` запускает самостоятельную критическую доработку; если без данных "
        f"пользователя нельзя продолжить, задай не более {profile.max_clarifying_questions} короткого вопроса.\n"
        "- `next` не означает приёмку текущего результата.\n"
        "- После `accept` сохрани в Obsidian только очищенный итог, решение, проверку, "
        "артефакты и следующий шаг; сырую переписку не сохраняй.\n"
        "- Публичные, финансовые, необратимые действия, секреты и массовые изменения "
        "выполняй только после отдельного подтверждения.\n"
        "- Пиши кратко: сначала результат, затем только проверка, риск или следующий шаг, "
        "которые меняют решение пользователя.\n"
        "- Отдели профиль интерфейса и callback-модель от Telegram token, framework, "
        "маршрутизации агентов и хранилища, чтобы профиль переносился без копипасты runtime."
    )


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    print(build_handoff_prompt())


if __name__ == "__main__":
    main()
