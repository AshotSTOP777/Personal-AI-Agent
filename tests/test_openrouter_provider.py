from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.openrouter_provider import OpenRouterProvider


def _make_provider() -> OpenRouterProvider:
    provider = OpenRouterProvider.__new__(OpenRouterProvider)  # обходим real AsyncOpenAI(api_key=...)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace()))
    provider._model = "openrouter/free"
    return provider


def _fake_response(content, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _tool_call(call_id: str, name: str, arguments_json: str):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments_json))


@pytest.mark.asyncio
async def test_generate_returns_text_when_no_tool_calls():
    provider = _make_provider()
    provider._client.chat.completions.create = AsyncMock(return_value=_fake_response("Привет!"))

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
    provider._client.chat.completions.create = AsyncMock(
        return_value=_fake_response(
            None, tool_calls=[_tool_call("call_1", "create_task", '{"title": "Позвонить"}')]
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
async def test_generate_sends_tool_result_as_tool_message():
    provider = _make_provider()
    captured = {}

    async def fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _fake_response("Готово")

    provider._client.chat.completions.create = fake_create

    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Создай задачу"}]},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call_1", "name": "create_task", "input": {"title": "X"}}],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "Создал"}]},
    ]

    await provider.generate(system="s", messages=messages, tools=[])

    sent = captured["messages"]
    assert sent[0] == {"role": "system", "content": "s"}
    assistant_msg = next(m for m in sent if m["role"] == "assistant")
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "create_task"
    tool_msg = next(m for m in sent if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"] == "Создал"
