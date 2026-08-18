from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider, ToolCall
from app.ai.system_prompt import build_system_prompt
from app.logging_setup import get_logger
from app.services import conversation_service, usage_service
from app.tools.base import ToolContext
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 10

# Явное разрешение выполнить внешнее действие (написать/отправить/связаться) содержится
# в исходном поручении пользователя — не нужно спрашивать "да" второй раз. PREPARE-глаголы
# имеют приоритет: "подготовь черновик и отправь" всё равно ничего не отправляет.
_EXECUTE_INTENT_KEYWORDS = (
    "напиши", "отправь", "свяжись", "закажи", "зарегистрируй", "предложи", "договорись",
    "поторгуйся", "попроси скидку", "узнай цену у", "напиши им", "напиши продавц", "send",
    "write to", "contact", "negotiate", "reach out",
)
_PREPARE_INTENT_KEYWORDS = (
    "подготовь", "составь", "покажи", "что бы ты написал", "черновик", "набросай", "draft", "prepare",
)


def _infers_execute_intent(text: str) -> bool:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _PREPARE_INTENT_KEYWORDS):
        return False
    return any(keyword in lowered for keyword in _EXECUTE_INTENT_KEYWORDS)


def _looks_like_raw_data(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("[") or stripped.startswith("{")


@dataclass
class CoordinatorResult:
    text: str
    pending_confirmation: dict[str, Any] | None = field(default=None)


@dataclass
class PendingAction:
    tool_call: ToolCall
    messages: list[dict[str, Any]]
    remaining_iterations: int


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
        self._pending: dict[int, PendingAction] = {}

    def has_pending(self, user_id: int) -> bool:
        return user_id in self._pending

    def clear_pending(self, user_id: int) -> None:
        self._pending.pop(user_id, None)

    async def handle_message(self, session: AsyncSession, user_id: int, user_text: str) -> CoordinatorResult:
        tokens_used = await usage_service.get_tokens_used_today(session, user_id)
        if tokens_used >= self._daily_token_limit:
            return CoordinatorResult(
                text="Достигнут дневной лимит токенов. Попробуй завтра или попроси владельца увеличить лимит."
            )

        # Новая задача отменяет любое незавершённое подтверждение от предыдущей.
        self._pending.pop(user_id, None)

        await conversation_service.add_message(session, user_id, "user", user_text)
        history = await conversation_service.get_recent_history(session, user_id, self._history_window)

        messages: list[dict[str, Any]] = [
            {"role": m.role, "content": [{"type": "text", "text": m.content}]} for m in history
        ]

        tool_defs = self._tools.anthropic_tool_definitions()
        ctx = ToolContext(user_id=user_id, session=session)

        return await self._run_loop(
            session, user_id, messages, tool_defs, ctx, MAX_TOOL_ITERATIONS,
            allow_confirm_bypass=_infers_execute_intent(user_text),
        )

    async def confirm_pending(self, session: AsyncSession, user_id: int) -> CoordinatorResult:
        """Выполняет ровно тот tool call, что был заблокирован на подтверждение, и
        продолжает agent loop с его результатом — без повторного планирования задачи моделью."""
        pending = self._pending.pop(user_id, None)
        if pending is None:
            return CoordinatorResult(text="Нет действия, ожидающего подтверждения.")

        ctx = ToolContext(user_id=user_id, session=session)
        result_text = await self._execute_tool(ctx, pending.tool_call.name, pending.tool_call.input)

        messages = pending.messages + [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": pending.tool_call.id, "content": result_text}
                ],
            }
        ]

        if pending.remaining_iterations <= 0:
            await conversation_service.add_message(session, user_id, "assistant", result_text)
            return CoordinatorResult(text=result_text)

        tool_defs = self._tools.anthropic_tool_definitions()
        return await self._run_loop(session, user_id, messages, tool_defs, ctx, pending.remaining_iterations)

    async def run_job_iteration(
        self,
        session: AsyncSession,
        user_id: int,
        messages: list[dict[str, Any]],
        max_iterations: int,
        goal: str,
    ) -> tuple[CoordinatorResult, PendingAction | None]:
        """Один прогон agent loop для фонового job. В отличие от handle_message, не трогает
        conversation_service (историю ведёт JobWorker через Job.context) и не использует
        self._pending (там место только для интерактивного чата, у каждого job — своё
        состояние в БД) — вместо этого возвращает PendingAction вызывающему."""
        tool_defs = self._tools.anthropic_tool_definitions()
        ctx = ToolContext(user_id=user_id, session=session)
        store: dict[int, PendingAction] = {}
        prompt = build_system_prompt(job_goal=goal)
        result = await self._run_loop(
            session, user_id, messages, tool_defs, ctx, max_iterations,
            persist=False, pending_store=store, system_prompt=prompt,
            allow_confirm_bypass=_infers_execute_intent(goal),
        )
        return result, store.get(user_id)

    async def confirm_job_pending(
        self, session: AsyncSession, user_id: int, pending: PendingAction
    ) -> tuple[CoordinatorResult, PendingAction | None]:
        """Аналог confirm_pending для job: выполняет сохранённый tool call и продолжает
        loop, не трогая conversation_service и self._pending."""
        ctx = ToolContext(user_id=user_id, session=session)
        result_text = await self._execute_tool(ctx, pending.tool_call.name, pending.tool_call.input)
        messages = pending.messages + [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": pending.tool_call.id, "content": result_text}
                ],
            }
        ]

        if pending.remaining_iterations <= 0:
            return CoordinatorResult(text=result_text), None

        tool_defs = self._tools.anthropic_tool_definitions()
        store: dict[int, PendingAction] = {}
        result = await self._run_loop(
            session, user_id, messages, tool_defs, ctx, pending.remaining_iterations,
            persist=False, pending_store=store,
        )
        return result, store.get(user_id)

    async def _run_loop(
        self,
        session: AsyncSession,
        user_id: int,
        messages: list[dict[str, Any]],
        tool_defs: list[dict[str, Any]],
        ctx: ToolContext,
        max_iterations: int,
        *,
        persist: bool = True,
        pending_store: dict[int, PendingAction] | None = None,
        system_prompt: str | None = None,
        allow_confirm_bypass: bool = False,
    ) -> CoordinatorResult:
        store = self._pending if pending_store is None else pending_store
        prompt = system_prompt or build_system_prompt()

        final_text = ""
        last_tool_summary = ""
        for iteration in range(max_iterations):
            response = await self._provider.generate(prompt, messages, tool_defs)

            await usage_service.log_usage(
                session, user_id, model=getattr(self._provider, "model_name", "unknown"),
                input_tokens=response.usage.input_tokens,
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
                (
                    tc for tc in response.tool_calls
                    if self._permission_of(tc).requires_confirmation
                    and not (allow_confirm_bypass and self._permission_of(tc) == PermissionLevel.CONFIRM)
                ),
                None,
            )
            if blocked_tool is not None:
                pending_messages = messages + [{"role": "assistant", "content": response.raw_content}]
                store[user_id] = PendingAction(
                    tool_call=blocked_tool,
                    messages=pending_messages,
                    remaining_iterations=max_iterations - iteration - 1,
                )
                return CoordinatorResult(
                    text=(
                        f"Требуется подтверждение для выполнения действия «{blocked_tool.name}» "
                        f"с параметрами {blocked_tool.input}. Напиши «да», чтобы подтвердить."
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
            last_tool_summary = "\n".join(block["content"] for block in tool_result_blocks)
            messages.append({"role": "user", "content": tool_result_blocks})
        else:
            final_text = "Не удалось завершить задачу за отведённое число шагов. Попробуй сформулировать проще."

        # Модель иногда вызывает инструмент и не даёт текстового резюме — вместо
        # молчаливого "Готово" показываем реальный результат последнего инструмента, но
        # никогда не дампим сырой JSON/tool output пользователю напрямую.
        if not final_text and last_tool_summary:
            final_text = (
                "Действие выполнено, но не удалось сформулировать краткий ответ. Уточни запрос."
                if _looks_like_raw_data(last_tool_summary)
                else last_tool_summary
            )
        if not final_text:
            final_text = "Не удалось получить ответ. Попробуй переформулировать запрос."

        if persist:
            await conversation_service.add_message(session, user_id, "assistant", final_text)
        return CoordinatorResult(text=final_text)

    def _permission_of(self, tool_call: ToolCall) -> PermissionLevel:
        tool = self._tools.get(tool_call.name)
        return tool.permission_for(tool_call.input) if tool else PermissionLevel.CRITICAL

    async def _execute_tool(self, ctx: ToolContext, name: str, args: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Инструмент '{name}' не найден."
        try:
            return await tool.run(ctx, **args)
        except Exception as exc:  # noqa: BLE001
            logger.error("tool_execution_failed", tool=name, error=str(exc))
            return f"Ошибка при выполнении инструмента '{name}': {exc}"
