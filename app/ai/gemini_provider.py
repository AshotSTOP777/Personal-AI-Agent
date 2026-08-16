from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

from app.ai.base import AIProvider, AIResponse, TokenUsage, ToolCall


def _tool_use_names(messages: list[dict[str, Any]]) -> dict[str, str]:
    """Coordinator не передаёт имя инструмента в tool_result-блоках (только tool_use_id),
    а Gemini FunctionResponse требует name. Восстанавливаем его из предыдущих tool_use."""
    names: dict[str, str] = {}
    for message in messages:
        for block in message["content"]:
            if block.get("type") == "tool_use":
                names[block["id"]] = block["name"]
    return names


def _blocks_to_gemini_content(role: str, blocks: list[dict[str, Any]], tool_names: dict[str, str]) -> types.Content:
    gemini_role = "model" if role == "assistant" else "user"
    parts: list[types.Part] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            parts.append(types.Part(text=block["text"]))
        elif block_type == "tool_use":
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(id=block["id"], name=block["name"], args=block["input"] or {})
                )
            )
        elif block_type == "tool_result":
            tool_use_id = block["tool_use_id"]
            parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=tool_use_id,
                        name=tool_names.get(tool_use_id, ""),
                        response={"result": block["content"]},
                    )
                )
            )
    return types.Content(role=gemini_role, parts=parts)


class GeminiProvider(AIProvider):
    """Провайдер на базе официального Google GenAI SDK. Реализует тот же интерфейс
    AIProvider, что и AnthropicProvider — Coordinator и инструменты не меняются."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> AIResponse:
        tool_names = _tool_use_names(messages)
        contents = [_blocks_to_gemini_content(m["role"], m["content"], tool_names) for m in messages]

        gemini_tools = None
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters_json_schema=tool["input_schema"],
                )
                for tool in tools
            ]
            gemini_tools = [types.Tool(function_declarations=declarations)]

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=gemini_tools,
                max_output_tokens=max_tokens,
            ),
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        raw_content: list[dict[str, Any]] = []

        candidate_parts = response.candidates[0].content.parts if response.candidates else []
        for index, part in enumerate(candidate_parts or []):
            if part.text:
                text_parts.append(part.text)
                raw_content.append({"type": "text", "text": part.text})
            elif part.function_call:
                call_id = part.function_call.id or f"{part.function_call.name}_{index}"
                args = part.function_call.args or {}
                tool_calls.append(ToolCall(id=call_id, name=part.function_call.name, input=dict(args)))
                raw_content.append(
                    {"type": "tool_use", "id": call_id, "name": part.function_call.name, "input": dict(args)}
                )

        usage = response.usage_metadata
        return AIResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw_content=raw_content,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=TokenUsage(
                input_tokens=usage.prompt_token_count or 0 if usage else 0,
                output_tokens=usage.candidates_token_count or 0 if usage else 0,
            ),
        )
