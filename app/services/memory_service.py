from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory


async def remember(session: AsyncSession, user_id: int, content: str, category: str = "general") -> Memory:
    memory = Memory(user_id=user_id, content=content, category=category)
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def recall(session: AsyncSession, user_id: int, query: str, limit: int = 5) -> list[Memory]:
    """Простой поиск по подстроке. В будущем можно заменить на embeddings/vector search."""
    stmt = (
        select(Memory)
        .where(Memory.user_id == user_id)
        .where(Memory.content.ilike(f"%{query}%"))
        .order_by(Memory.updated_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    memories = list(result.scalars().all())
    if memories:
        return memories

    # Фолбэк: если по подстроке ничего не нашлось, возвращаем последние записи —
    # модель сама решит, что из них релевантно.
    stmt = select(Memory).where(Memory.user_id == user_id).order_by(Memory.updated_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
