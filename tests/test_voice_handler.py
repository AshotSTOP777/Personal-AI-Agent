from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.coordinator import CoordinatorResult
from app.bot import handlers as handlers_module
from app.bot.handlers import handle_voice_message

MAX_DURATION = 300


def _make_message(voice_duration: int | None = 10) -> SimpleNamespace:
    voice = SimpleNamespace(file_id="file123", duration=voice_duration) if voice_duration is not None else None
    return SimpleNamespace(
        voice=voice,
        audio=None,
        from_user=SimpleNamespace(id=1),
        chat=SimpleNamespace(id=1),
        answer=AsyncMock(),
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
    )


@pytest.fixture(autouse=True)
def _patch_session_scope(monkeypatch):
    @asynccontextmanager
    async def fake_session_scope():
        yield object()

    monkeypatch.setattr(handlers_module, "session_scope", fake_session_scope)


@pytest.fixture(autouse=True)
def _patch_download(monkeypatch):
    monkeypatch.setattr(handlers_module, "_download_voice", AsyncMock(return_value=b"fake-audio"))


@pytest.mark.asyncio
async def test_voice_over_duration_limit_is_rejected_without_stt_call():
    message = _make_message(voice_duration=MAX_DURATION + 60)
    stt_provider = SimpleNamespace(transcribe=AsyncMock())
    coordinator = AsyncMock()

    await handle_voice_message(message, coordinator, stt_provider, MAX_DURATION)

    stt_provider.transcribe.assert_not_awaited()
    coordinator.handle_message.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert "5 минут" in message.answer.call_args.args[0] or "минут" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_voice_without_configured_stt_notifies_owner():
    message = _make_message()
    coordinator = AsyncMock()

    await handle_voice_message(message, coordinator, None, MAX_DURATION)

    coordinator.handle_message.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert "не настроено" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_voice_transcribed_text_is_passed_to_coordinator_like_normal_message():
    message = _make_message()
    stt_provider = SimpleNamespace(transcribe=AsyncMock(return_value="Позвони маме завтра"))
    coordinator = SimpleNamespace(
        handle_message=AsyncMock(return_value=CoordinatorResult(text="Хорошо, напомню позвонить маме."))
    )

    await handle_voice_message(message, coordinator, stt_provider, MAX_DURATION)

    stt_provider.transcribe.assert_awaited_once_with(b"fake-audio", filename="voice.ogg")
    coordinator.handle_message.assert_awaited_once()
    _, called_user_id, called_text = coordinator.handle_message.call_args.args
    assert called_user_id == 1
    assert called_text == "Позвони маме завтра"
    message.answer.assert_awaited_once_with("Хорошо, напомню позвонить маме.")


@pytest.mark.asyncio
async def test_voice_stt_error_notifies_owner_and_skips_coordinator():
    message = _make_message()
    stt_provider = SimpleNamespace(transcribe=AsyncMock(side_effect=RuntimeError("stt down")))
    coordinator = AsyncMock()

    await handle_voice_message(message, coordinator, stt_provider, MAX_DURATION)

    coordinator.handle_message.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert "распознать" in message.answer.call_args.args[0].lower()
