from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.stt.factory import build_stt_provider
from app.stt.groq_provider import GroqWhisperProvider
from app.stt.openrouter_provider import OpenRouterSTTProvider


def test_build_stt_provider_returns_none_when_key_missing():
    settings = Settings(stt_provider="groq", groq_api_key="")
    assert build_stt_provider(settings) is None


def test_build_stt_provider_returns_none_for_unknown_provider():
    settings = Settings(stt_provider="unknown", groq_api_key="fake")
    assert build_stt_provider(settings) is None


def test_build_stt_provider_returns_groq_when_configured():
    settings = Settings(stt_provider="groq", groq_api_key="fake-groq-key", stt_model="whisper-large-v3-turbo")
    provider = build_stt_provider(settings)
    assert isinstance(provider, GroqWhisperProvider)


def test_build_stt_provider_returns_none_when_openrouter_key_missing():
    settings = Settings(stt_provider="openrouter", openrouter_api_key="")
    assert build_stt_provider(settings) is None


def test_build_stt_provider_returns_openrouter_when_configured():
    settings = Settings(
        stt_provider="openrouter", openrouter_api_key="fake-openrouter-key", stt_model="openai/whisper-large-v3:free"
    )
    provider = build_stt_provider(settings)
    assert isinstance(provider, OpenRouterSTTProvider)


@pytest.mark.asyncio
async def test_openrouter_provider_transcribe_returns_text():
    provider = OpenRouterSTTProvider.__new__(OpenRouterSTTProvider)  # обходим real AsyncOpenAI(api_key=...)
    provider._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace()))
    provider._model = "openai/whisper-large-v3:free"
    provider._client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="Позвони маме завтра")
    )

    text = await provider.transcribe(b"fake-audio-bytes", filename="voice.ogg")

    assert text == "Позвони маме завтра"


@pytest.mark.asyncio
async def test_groq_provider_transcribe_returns_text():
    provider = GroqWhisperProvider.__new__(GroqWhisperProvider)  # обходим real AsyncOpenAI(api_key=...)
    provider._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace()))
    provider._model = "whisper-large-v3-turbo"
    provider._client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="Позвони маме завтра")
    )

    text = await provider.transcribe(b"fake-audio-bytes", filename="voice.ogg")

    assert text == "Позвони маме завтра"


@pytest.mark.asyncio
async def test_groq_provider_transcribe_propagates_errors():
    provider = GroqWhisperProvider.__new__(GroqWhisperProvider)
    provider._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace()))
    provider._model = "whisper-large-v3-turbo"
    provider._client.audio.transcriptions.create = AsyncMock(side_effect=RuntimeError("stt down"))

    with pytest.raises(RuntimeError):
        await provider.transcribe(b"fake-audio-bytes", filename="voice.ogg")
