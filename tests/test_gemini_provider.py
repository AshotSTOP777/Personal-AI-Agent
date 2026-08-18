from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.gemini_provider import GeminiProvider


def _make_provider() -> GeminiProvider:
    provider = GeminiProvider.__new__(GeminiProvider)  # обходим real genai.Client(api_key=...)
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace()))
    provider._model = "gemini-2.5-flash"
    return provider


def _fake_response(parts, prompt_tokens=10, candidates_tokens=5):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))],
        usage_metadata=SimpleNamespace(prompt_token_count=prompt_tokens, candidates_token_count=candidates_tokens),
    )


def _text_part(text: str):
    return SimpleNamespace(text=text, function_call=None)


def _function_call_part(call_id: str, name: str, args: dict):
    fc = SimpleNamespace(id=call_id, name=name, args=args)
    return SimpleNamespace(text=None, function_call=fc)


def _thought_part(text: str):
    return SimpleNamespace(text=text, function_call=None, thought=True)


@pytest.mark.asyncio
async def test_generate_returns_text_when_no_tool_calls():
    provider = _make_provider()
    provider._client.aio.models.generate_content = AsyncMock(
        return_value=_fake_response([_text_part("Привет!")])
    )

    result = await provider.generate(
        system="системный промпт",
        messages=[{"role": "user", "content": [{"type": "text", "text": "Привет"}]}],
        tools=[],
    )

    assert result.text == "Привет!"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5


@pytest.mark.asyncio
async def test_generate_parses_tool_call():
    provider = _make_provider()
    provider._client.aio.models.generate_content = AsyncMock(
        return_value=_fake_response(
            [_function_call_part("call_1", "create_task", {"title": "Позвонить"})]
        )
    )

    result = await provider.generate(
        system="системный промпт",
        messages=[{"role": "user", "content": [{"type": "text", "text": "Создай задачу"}]}],
        tools=[{"name": "create_task", "description": "...", "input_schema": {"type": "object"}}],
    )

    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "create_task"
    assert result.tool_calls[0].input == {"title": "Позвонить"}
    assert result.raw_content[0]["type"] == "tool_use"


@pytest.mark.asyncio
async def test_generate_sends_tool_result_with_recovered_name():
    provider = _make_provider()
    captured = {}

    async def fake_generate_content(**kwargs):
        captured["contents"] = kwargs["contents"]
        return _fake_response([_text_part("Готово")])

    provider._client.aio.models.generate_content = fake_generate_content

    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Создай задачу"}]},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call_1", "name": "create_task", "input": {"title": "X"}}],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "Создал"}]},
    ]

    await provider.generate(system="s", messages=messages, tools=[])

    tool_result_content = captured["contents"][-1]
    function_response_part = tool_result_content.parts[0]
    assert function_response_part.function_response.name == "create_task"
    assert function_response_part.function_response.response == {"result": "Создал"}


@pytest.mark.asyncio
async def test_generate_skips_thought_parts():
    provider = _make_provider()
    provider._client.aio.models.generate_content = AsyncMock(
        return_value=_fake_response([_thought_part("рассуждаю много букв"), _text_part("Финальный ответ")])
    )

    result = await provider.generate(
        system="системный промпт",
        messages=[{"role": "user", "content": [{"type": "text", "text": "Привет"}]}],
        tools=[],
    )

    assert result.text == "Финальный ответ"
    assert "рассуждаю" not in result.text
