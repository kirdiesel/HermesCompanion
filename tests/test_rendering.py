from tg_companion_bot.rendering import (
    ACCEPTED_STATUS,
    DONE_STATUS,
    IN_PROGRESS_STATUS,
    REVIEW_STATUS,
    Button,
    RenderRequest,
    render_message,
)


def test_final_result_gets_review_status_and_acceptance_buttons():
    rendered = render_message(
        RenderRequest(
            kind="final_result",
            title="Проверить импорт Obsidian",
            done=["Создан бриф", "Создан манифест"],
            verified=["Файлы читаются"],
            next_step="Начать renderer кнопок",
        )
    )

    assert rendered.status == REVIEW_STATUS
    assert "🔎 приёмка" in rendered.text
    assert "Проверить импорт Obsidian" in rendered.text
    assert "Создан бриф" in rendered.text
    assert rendered.buttons == [
        Button(text="Принять результат", action="accept"),
        Button(text="Доработать результат", action="revise"),
        Button(text="Показать следующий шаг", action="next"),
    ]


def test_progress_message_has_no_buttons():
    rendered = render_message(
        RenderRequest(
            kind="progress",
            title="Проверяю файлы проекта",
            done=["Нашла README"],
        )
    )

    assert rendered.status == IN_PROGRESS_STATUS
    assert "▶️ выполняется" in rendered.text
    assert rendered.buttons == []


def test_simple_information_message_has_no_buttons():
    rendered = render_message(
        RenderRequest(
            kind="info",
            title="Статус проекта",
            done=["Кодового проекта пока нет"],
        )
    )

    assert rendered.status == ACCEPTED_STATUS
    assert rendered.buttons == []


def test_accepted_result_gets_done_status_without_keyboard():
    rendered = render_message(
        RenderRequest(
            kind="accepted",
            title="Пользователь принял результат",
            done=["Итог записан в Obsidian"],
            next_step="Продолжить по backlog",
        )
    )

    assert rendered.status == DONE_STATUS
    assert "✅ готово" in rendered.text
    assert rendered.buttons == []
    assert "Продолжить по backlog" in rendered.text
