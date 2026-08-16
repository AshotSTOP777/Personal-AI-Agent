from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel

Role = Literal["user", "assistant"]


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class AIResponse(BaseModel):
    """Ответ AI-провайдера.

    text — финальный текст ответа (может быть пустым, если модель запросила инструменты).
    tool_calls — инструменты, которые модель хочет вызвать.
    raw_content — блоки контента в исходном формате провайдера, нужны, чтобы корректно
        продолжить диалог (добавить в историю как assistant turn) при цепочке вызовов инструментов.
    """

    text: str
    tool_calls: list[ToolCall]
    raw_content: list[dict[str, Any]]
    stop_reason: str
    usage: TokenUsage


class AIProvider(ABC):
    """Абстракция над LLM-бэкендом. Позволяет заменить Claude на другой провайдер,
    не меняя Coordinator и инструменты."""

    @abstractmethod
    async def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> AIResponse:
        """Отправляет сообщения модели и возвращает структурированный ответ.

        Формат messages: [{"role": "user"|"assistant", "content": [...blocks]}]
        Блоки: {"type": "text", "text": str} | {"type": "tool_use", "id", "name", "input"}
               | {"type": "tool_result", "tool_use_id", "content"}
        """
        raise NotImplementedError
