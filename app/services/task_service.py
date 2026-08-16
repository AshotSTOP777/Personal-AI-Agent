from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus


async def create_task(
    session: AsyncSession,
    user_id: int,
    title: str,
    description: str | None = None,
    due_date: dt.datetime | None = None,
) -> Task:
    task = Task(user_id=user_id, title=title, description=description, due_date=due_date)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def list_active_tasks(session: AsyncSession, user_id: int) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.user_id == user_id, Task.status == TaskStatus.ACTIVE)
        .order_by(Task.created_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def complete_task(session: AsyncSession, user_id: int, task_id: int) -> Task | None:
    stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        return None
    task.status = TaskStatus.COMPLETED
    task.completed_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()
    await session.refresh(task)
    return task
