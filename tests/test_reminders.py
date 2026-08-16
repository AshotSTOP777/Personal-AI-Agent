from __future__ import annotations

import datetime as dt

import pytest

from app.services import reminder_service


@pytest.mark.asyncio
async def test_create_reminder(db_session):
    remind_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    reminder = await reminder_service.create_reminder(db_session, user_id=1, text="Позвонить", remind_at=remind_at)
    assert reminder.id is not None
    assert reminder.status.value == "pending"


@pytest.mark.asyncio
async def test_list_due_reminders_only_returns_past_due(db_session):
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    await reminder_service.create_reminder(db_session, user_id=1, text="Просрочено", remind_at=past)
    await reminder_service.create_reminder(db_session, user_id=1, text="Будущее", remind_at=future)

    due = await reminder_service.list_due_reminders(db_session)
    assert len(due) == 1
    assert due[0].text == "Просрочено"


@pytest.mark.asyncio
async def test_mark_sent_updates_status(db_session):
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    reminder = await reminder_service.create_reminder(db_session, user_id=1, text="Напоминание", remind_at=past)

    await reminder_service.mark_sent(db_session, reminder.id)

    due = await reminder_service.list_due_reminders(db_session)
    assert due == []
