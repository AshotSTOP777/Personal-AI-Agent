from __future__ import annotations

from app.bot.formatting import strip_markdown


def test_strip_markdown_removes_bold_and_italic():
    assert strip_markdown("**жирный** и _курсив_") == "жирный и курсив"


def test_strip_markdown_removes_code_and_headings():
    text = "## Заголовок\nвот `код` и обычный текст"
    result = strip_markdown(text)
    assert "#" not in result
    assert "`" not in result
    assert "код" in result


def test_strip_markdown_leaves_plain_text_untouched():
    assert strip_markdown("Обычный ответ без разметки.") == "Обычный ответ без разметки."
