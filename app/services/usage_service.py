from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import AiUsageLog


async def log_usage(session: AsyncSession, user_id: int, model: str, input_tokens: int, output_tokens: int) -> None:
    session.add(AiUsageLog(user_id=user_id, model=model, input_tokens=input_tokens, output_tokens=output_tokens))
    await session.commit()


async def get_tokens_used_today(session: AsyncSession, user_id: int) -> int:
    start_of_day = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(
        func.coalesce(func.sum(AiUsageLog.input_tokens + AiUsageLog.output_tokens), 0)
    ).where(AiUsageLog.user_id == user_id, AiUsageLog.created_at >= start_of_day)
    result = await session.execute(stmt)
    return int(result.scalar_one())
