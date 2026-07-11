from dataclasses import replace
from pathlib import Path

from tg_companion_bot.interaction_profile import (
    DEFAULT_INTERACTION_PROFILE,
    ActionLabel,
    build_handoff_prompt,
)
from tg_companion_bot.rendering import RenderRequest, render_message


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_custom_profile_changes_labels_without_changing_renderer_code():
    profile = replace(
        DEFAULT_INTERACTION_PROFILE,
        actions=(
            ActionLabel("accept", "Подтвердить"),
            ActionLabel("revise", "Исправить"),
            ActionLabel("next", "Продолжить"),
        ),
    )

    rendered = render_message(
        RenderRequest(kind="final_result", title="Результат", done=["Готово"]),
        profile=profile,
    )

    assert [button.text for button in rendered.buttons] == ["Подтвердить", "Исправить", "Продолжить"]


def test_handoff_prompt_is_portable_and_contains_the_full_acceptance_cycle():
    prompt = build_handoff_prompt()

    assert "задача -> результат -> приёмка -> Obsidian -> следующий шаг" in prompt
    assert "Принять результат" in prompt
    assert "Доработать результат" in prompt
    assert "Показать следующий шаг" in prompt
    assert "Кирилл" not in prompt
    assert "C:\\AIProjects" not in prompt


def test_ready_handoff_document_matches_portable_contract():
    document = (PROJECT_ROOT / "docs" / "hermes_one_interface_prompt.md").read_text(encoding="utf-8")

    assert "Один переносимый промпт" in document
    assert "задача -> результат -> приёмка -> Obsidian -> следующий шаг" in document
    assert "Кирилл" not in document
