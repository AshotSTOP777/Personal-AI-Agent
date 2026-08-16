from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.system_prompt import SYSTEM_PROMPT
from app.logging_setup import get_logger
from app.services import conversation_service, usage_service
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry
from app.tools.permissions import PermissionLevel

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 5


@dataclass
class CoordinatorResult:
    text: str
    pending_confirmation: dict[str, Any] | None = field(default=None)


class DailyLimitExceeded(Exception):
    pass


class Coordinator:
    """Главный агент. Ведёт диалог, вызывает инструменты, следит за лимитом токенов.

    В будущем сюда можно добавить временных специалистов (Researcher, Analyst,
    Developer, Personal Assistant), которых Coordinator будет вызывать под конкретную
    задачу, не меняя публичный интерфейс handle_message.
    """

    def __init__(
        self,
        provider: AIProvider,
        tool_registry: ToolRegistry,
        history_window: int,
        daily_token_limit: int,
    ) -> None:
        self._provider = provider
        self._tools = tool_registry
        self._history_window = history_window
        self._daily_token_limit = daily_token_limit

    async def handle_message(self, session: AsyncSession, user_id: int, user_text: str) -> CoordinatorResult:
        tokens_used = await usage_service.get_tokens_used_today(session, user_id)
        if tokens_used >= self._daily_token_limit:
            return CoordinatorResult(
                text="Достигнут дневной лимит токенов. Попробуй завтра или попроси владельца увеличить лимит."
            )

        await conversation_service.add_message(session, user_id, "user", user_text)
        history = await conversation_service.get_recent_history(session, user_id, self._history_window)

        messages: list[dict[str, Any]] = [
            {"role": m.role, "content": [{"type": "text", "text": m.content}]} for m in history
        ]

        tool_defs = self._tools.anthropic_tool_definitions()
        ctx = ToolContext(user_id=user_id, session=session)

        final_text = ""
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await self._provider.generate(SYSTEM_PROMPT, messages, tool_defs)

            await usage_service.log_usage(
                session, user_id, model="claude", input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            logger.info(
                "ai_usage",
                user_id=user_id,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            if not response.tool_calls:
                final_text = response.text
                break

            blocked_tool = next(
                (tc for tc in response.tool_calls if self._permission_of(tc.name).requires_confirmation),
                None,
            )
            if blocked_tool is not None:
                return CoordinatorResult(
                    text=(
                        f"Требуется подтверждение для выполнения действия «{blocked_tool.name}» "
                        f"с параметрами {blocked_tool.input}. Подтверди выполнение."
                    ),
                    pending_confirmation={"tool_name": blocked_tool.name, "input": blocked_tool.input},
                )

            messages.append({"role": "assistant", "content": response.raw_content})

            tool_result_blocks = []
            for tool_call in response.tool_calls:
                result_text = await self._execute_tool(ctx, tool_call.name, tool_call.input)
                tool_result_blocks.append(
                    {"type": "tool_result", "tool_use_id": tool_call.id, "content": result_text}
                )
            messages.append({"role": "user", "content": tool_result_blocks})
        else:
            final_text = "Не удалось завершить задачу за отведённое число шагов. Попробуй сформулировать проще."

        if final_text:
            await conversation_service.add_message(session, user_id, "assistant", final_text)

        return CoordinatorResult(text=final_text)

    def _permission_of(self, tool_name: str) -> PermissionLevel:
        tool = self._tools.get(tool_name)
        return tool.permission if tool else PermissionLevel.CRITICAL

    async def _execute_tool(self, ctx: ToolContext, name: str, args: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Инструмент '{name}' не найден."
        try:
            return await tool.run(ctx, **args)
        except Exception as exc:  # noqa: BLE001
            logger.error("tool_execution_failed", tool=name, error=str(exc))
            return f"Ошибка при выполнении инструмента '{name}': {exc}"
