from __future__ import annotations

from app.tools.base import Tool


class ToolRegistry:
    """Явный реестр доступных инструментов."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Инструмент '{tool.name}' уже зарегистрирован")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def anthropic_tool_definitions(self) -> list[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema(),
            }
            for tool in self._tools.values()
        ]


def _build_default_registry() -> ToolRegistry:
    from app.tools.complete_task import CompleteTaskTool
    from app.tools.create_reminder import CreateReminderTool
    from app.tools.create_task import CreateTaskTool
    from app.tools.list_tasks import ListTasksTool
    from app.tools.recall_memory import RecallMemoryTool
    from app.tools.remember import RememberTool
    from app.tools.web_search import WebSearchTool

    registry = ToolRegistry()
    for tool_cls in (
        RememberTool,
        RecallMemoryTool,
        CreateTaskTool,
        ListTasksTool,
        CompleteTaskTool,
        CreateReminderTool,
        WebSearchTool,
    ):
        registry.register(tool_cls())
    return registry


default_registry = _build_default_registry()
