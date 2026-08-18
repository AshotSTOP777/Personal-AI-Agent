from __future__ import annotations

import datetime as dt

import pytest

from app.tools.base import ToolContext
from app.tools.create_reminder import CreateReminderTool


@pytest.mark.asyncio
async def test_naive_datetime_interpreted_as_user_timezone_not_utc(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.create_reminder.settings.user_timezone", "Europe/Moscow")
    tool = CreateReminderTool()
    ctx = ToolContext(user_id=1, session=db_session)

    # 15:00 без tz должно стать 12:00 UTC (Москва = UTC+3), а не остаться 15:00 UTC.
    result = await tool.run(ctx, text="Позвонить", remind_at="2026-01-10T15:00:00")

    from app.services import reminder_service

    due = await reminder_service.list_due_reminders(
        db_session, now=dt.datetime(2026, 1, 10, 12, 1, tzinfo=dt.timezone.utc)
    )
    assert len(due) == 1
    assert due[0].remind_at.hour == 12  # сохранено в UTC
    assert "15:00" in result  # но показано владельцу в его локальном времени


@pytest.mark.asyncio
async def test_aware_datetime_kept_as_is(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.create_reminder.settings.user_timezone", "Europe/Moscow")
    tool = CreateReminderTool()
    ctx = ToolContext(user_id=1, session=db_session)

    await tool.run(ctx, text="Встреча", remind_at="2026-01-10T12:00:00+00:00")

    from app.services import reminder_service

    due = await reminder_service.list_due_reminders(
        db_session, now=dt.datetime(2026, 1, 10, 12, 1, tzinfo=dt.timezone.utc)
    )
    assert len(due) == 1
    assert due[0].remind_at.hour == 12
