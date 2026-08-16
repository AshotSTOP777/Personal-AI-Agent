from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder, ReminderStatus


async def create_reminder(session: AsyncSession, user_id: int, text: str, remind_at: dt.datetime) -> Reminder:
    reminder = Reminder(user_id=user_id, text=text, remind_at=remind_at)
    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)
    return reminder


async def list_due_reminders(session: AsyncSession, now: dt.datetime | None = None) -> list[Reminder]:
    now = now or dt.datetime.now(dt.timezone.utc)
    stmt = select(Reminder).where(Reminder.status == ReminderStatus.PENDING, Reminder.remind_at <= now)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_sent(session: AsyncSession, reminder_id: int) -> None:
    stmt = select(Reminder).where(Reminder.id == reminder_id)
    result = await session.execute(stmt)
    reminder = result.scalar_one_or_none()
    if reminder is None:
        return
    reminder.status = ReminderStatus.SENT
    reminder.sent_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()
