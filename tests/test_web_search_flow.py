from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.ai.base import AIResponse, TokenUsage, ToolCall
from app.ai.coordinator import Coordinator
from app.tools.registry import default_registry

DUCKDUCKGO_HTML = """
<a class="result__a" href="https://example.com/article">Пример статьи про X</a>
<a class="result__snippet" href="#">Краткое описание статьи о теме X.</a>
"""


class ScriptedProvider:
    def __init__(self, responses: list[AIResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def generate(self, system, messages, tools, max_tokens=1024) -> AIResponse:
        self.calls.append({"messages": messages, "tools": tools})
        return self._responses.pop(0)


def _usage() -> TokenUsage:
    return TokenUsage(input_tokens=10, output_tokens=5)


@pytest.mark.asyncio
async def test_explicit_web_request_calls_web_search_and_returns_real_result(db_session, monkeypatch):
    """Явный запрос 'найди в интернете' должен привести к вызову web_search, а финальный
    ответ должен содержать реальный результат (ссылку), а не заглушку 'Готово.'."""

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=DUCKDUCKGO_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tool_call_response = AIResponse(
        text="",
        tool_calls=[ToolCall(id="call_1", name="web_search", input={"query": "новости про X"})],
        raw_content=[
            {"type": "tool_use", "id": "call_1", "name": "web_search", "input": {"query": "новости про X"}}
        ],
        stop_reason="tool_use",
        usage=_usage(),
    )
    final_response = AIResponse(
        text="Нашёл статью «Пример статьи про X»: https://example.com/article",
        tool_calls=[],
        raw_content=[{"type": "text", "text": "Нашёл статью «Пример статьи про X»: https://example.com/article"}],
        stop_reason="end_turn",
        usage=_usage(),
    )
    provider = ScriptedProvider([tool_call_response, final_response])
    coordinator = Coordinator(
        provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000
    )

    result = await coordinator.handle_message(
        db_session, user_id=1, user_text="Найди в интернете последние новости про X"
    )

    assert len(provider.calls) == 2
    assert "example.com/article" in result.text
    assert result.text != "Готово."


@pytest.mark.asyncio
async def test_final_text_falls_back_to_real_tool_result_when_model_gives_no_summary(db_session):
    """Если модель после tool call не дала текстового резюме, Coordinator должен вернуть
    реальный результат инструмента, а не пустой ответ / заглушку."""
    tool_call_response = AIResponse(
        text="",
        tool_calls=[ToolCall(id="call_1", name="list_tasks", input={})],
        raw_content=[{"type": "tool_use", "id": "call_1", "name": "list_tasks", "input": {}}],
        stop_reason="tool_use",
        usage=_usage(),
    )
    empty_final_response = AIResponse(
        text="",
        tool_calls=[],
        raw_content=[],
        stop_reason="end_turn",
        usage=_usage(),
    )
    provider = ScriptedProvider([tool_call_response, empty_final_response])
    coordinator = Coordinator(
        provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000
    )

    result = await coordinator.handle_message(db_session, user_id=1, user_text="Какие у меня задачи?")

    assert result.text == "Активных задач нет."
    assert result.text != "Готово."
