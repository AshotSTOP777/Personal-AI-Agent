from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import ConversationMessage


async def add_message(session: AsyncSession, user_id: int, role: str, content: str) -> ConversationMessage:
    message = ConversationMessage(user_id=user_id, role=role, content=content)
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def get_recent_history(session: AsyncSession, user_id: int, limit: int) -> list[ConversationMessage]:
    """Возвращает последние `limit` сообщений в хронологическом порядке (старые -> новые)."""
    stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.user_id == user_id)
        .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()
    return messages
