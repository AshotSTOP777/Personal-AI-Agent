from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.ai.base import AIProvider, AIResponse, TokenUsage, ToolCall

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _blocks_to_openai_messages(role: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Конвертирует один generic-message (role + blocks) в один или несколько сообщений
    в формате OpenAI Chat Completions (tool_result всегда отдельным role="tool" сообщением)."""
    if role == "assistant":
        text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
        tool_calls = [
            {
                "id": b["id"],
                "type": "function",
                "function": {"name": b["name"], "arguments": json.dumps(b["input"] or {})},
            }
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        message: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return [message]

    messages: list[dict[str, Any]] = []
    text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
    if text_parts:
        messages.append({"role": "user", "content": "\n".join(text_parts)})
    for block in blocks:
        if block.get("type") == "tool_result":
            messages.append(
                {"role": "tool", "tool_call_id": block["tool_use_id"], "content": str(block["content"])}
            )
    return messages


class OpenRouterProvider(AIProvider):
    """Провайдер поверх OpenAI-совместимого API OpenRouter. Реализует тот же интерфейс
    AIProvider, что и AnthropicProvider/GeminiProvider — Coordinator и инструменты не меняются."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
        self._model = model

    async def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> AIResponse:
        openai_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for message in messages:
            openai_messages.extend(_blocks_to_openai_messages(message["role"], message["content"]))

        openai_tools = (
            [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
                for tool in tools
            ]
            if tools
            else None
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=openai_messages,
            tools=openai_tools,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls: list[ToolCall] = []
        raw_content: list[dict[str, Any]] = []

        if text:
            raw_content.append({"type": "text", "text": text})

        for tool_call in choice.message.tool_calls or []:
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tool_call.id, name=tool_call.function.name, input=args))
            raw_content.append(
                {"type": "tool_use", "id": tool_call.id, "name": tool_call.function.name, "input": args}
            )

        usage = response.usage
        return AIResponse(
            text=text,
            tool_calls=tool_calls,
            raw_content=raw_content,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=TokenUsage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
        )
