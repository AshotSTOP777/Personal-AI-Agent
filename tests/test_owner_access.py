from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.bot.middlewares import OwnerOnlyMiddleware

OWNER_ID = 111


class FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeEvent:
    def __init__(self) -> None:
        self.answer = AsyncMock()


@pytest.mark.asyncio
async def test_owner_request_is_forwarded_to_handler():
    middleware = OwnerOnlyMiddleware(OWNER_ID)
    handler = AsyncMock(return_value="ok")
    event = FakeEvent()

    result = await middleware(handler, event, {"event_from_user": FakeUser(OWNER_ID)})

    handler.assert_awaited_once()
    assert result == "ok"


@pytest.mark.asyncio
async def test_non_owner_request_is_blocked():
    middleware = OwnerOnlyMiddleware(OWNER_ID)
    handler = AsyncMock(return_value="ok")
    event = FakeEvent()

    result = await middleware(handler, event, {"event_from_user": FakeUser(999)})

    handler.assert_not_awaited()
    event.answer.assert_awaited_once()
    assert result is None
