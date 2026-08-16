from __future__ import annotations

import pytest

from app.services import memory_service


@pytest.mark.asyncio
async def test_remember_saves_fact(db_session):
    memory = await memory_service.remember(db_session, user_id=1, content="Сервер на Hetzner", category="работа")
    assert memory.id is not None
    assert memory.content == "Сервер на Hetzner"
    assert memory.category == "работа"


@pytest.mark.asyncio
async def test_recall_finds_by_substring(db_session):
    # Используем совпадающий регистр: LOWER() в SQLite не приводит кириллицу,
    # в отличие от PostgreSQL (используется в проде), где ILIKE учитывает юникод.
    await memory_service.remember(db_session, user_id=1, content="сервер находится в германии")
    await memory_service.remember(db_session, user_id=1, content="любимый цвет — синий")

    results = await memory_service.recall(db_session, user_id=1, query="сервер")
    assert len(results) == 1
    assert "германии" in results[0].content


@pytest.mark.asyncio
async def test_recall_isolated_per_user(db_session):
    await memory_service.remember(db_session, user_id=1, content="Факт пользователя 1")
    await memory_service.remember(db_session, user_id=2, content="Факт пользователя 2")

    results = await memory_service.recall(db_session, user_id=1, query="", limit=10)
    assert all(m.user_id == 1 for m in results)
