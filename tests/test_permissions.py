from __future__ import annotations

from app.tools.permissions import PermissionLevel
from app.tools.registry import default_registry


def test_safe_does_not_require_confirmation():
    assert PermissionLevel.SAFE.requires_confirmation is False


def test_confirm_and_critical_require_confirmation():
    assert PermissionLevel.CONFIRM.requires_confirmation is True
    assert PermissionLevel.CRITICAL.requires_confirmation is True


_CONFIRM_TOOLS = {"email_send", "browser_submit", "avito_send_messages"}


def test_default_registry_tools_are_safe_unless_explicitly_risky():
    """Только явно рискованные действия (отправка email, submit формы) требуют подтверждения."""
    for tool in default_registry.all():
        expected = PermissionLevel.CONFIRM if tool.name in _CONFIRM_TOOLS else PermissionLevel.SAFE
        assert tool.permission == expected, tool.name


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
        "browser_open",
        "browser_read",
        "browser_click",
        "browser_type",
        "browser_submit",
        "browser_current_url",
        "email_send",
        "email_read_recent",
        "email_search",
        "create_job",
        "avito_search",
        "avito_read_listing",
        "avito_prepare_messages",
        "avito_send_messages",
        "site_extract",
        "site_login_status",
    }
