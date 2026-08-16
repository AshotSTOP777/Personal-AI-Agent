from __future__ import annotations

import pytest

from app.services import task_service


@pytest.mark.asyncio
async def test_create_task(db_session):
    task = await task_service.create_task(db_session, user_id=1, title="Подготовить отчёт")
    assert task.id is not None
    assert task.status.value == "active"


@pytest.mark.asyncio
async def test_list_active_tasks_excludes_completed(db_session):
    t1 = await task_service.create_task(db_session, user_id=1, title="Задача 1")
    await task_service.create_task(db_session, user_id=1, title="Задача 2")
    await task_service.complete_task(db_session, user_id=1, task_id=t1.id)

    active = await task_service.list_active_tasks(db_session, user_id=1)
    assert len(active) == 1
    assert active[0].title == "Задача 2"


@pytest.mark.asyncio
async def test_complete_task_marks_completed(db_session):
    task = await task_service.create_task(db_session, user_id=1, title="Задача")
    completed = await task_service.complete_task(db_session, user_id=1, task_id=task.id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_complete_task_wrong_user_returns_none(db_session):
    task = await task_service.create_task(db_session, user_id=1, title="Задача")
    result = await task_service.complete_task(db_session, user_id=999, task_id=task.id)
    assert result is None
