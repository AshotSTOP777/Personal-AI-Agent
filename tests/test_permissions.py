from __future__ import annotations

from app.tools.permissions import PermissionLevel
from app.tools.registry import default_registry


def test_safe_does_not_require_confirmation():
    assert PermissionLevel.SAFE.requires_confirmation is False


def test_confirm_and_critical_require_confirmation():
    assert PermissionLevel.CONFIRM.requires_confirmation is True
    assert PermissionLevel.CRITICAL.requires_confirmation is True


def test_default_registry_tools_are_safe():
    """Все текущие инструменты первой версии не должны требовать подтверждения."""
    for tool in default_registry.all():
        assert tool.permission == PermissionLevel.SAFE


def test_registry_contains_expected_tools():
    names = {tool.name for tool in default_registry.all()}
    assert names == {
        "remember",
        "recall_memory",
        "create_task",
        "list_tasks",
        "complete_task",
        "create_reminder",
        "web_search",
        "fetch_page",
    }
