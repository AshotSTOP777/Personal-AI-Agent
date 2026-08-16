from __future__ import annotations

from openai import AsyncOpenAI

from app.stt.base import STTProvider

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqWhisperProvider(STTProvider):
    """Speech-to-text через Groq Whisper по OpenAI-совместимому API."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
        self._model = model

    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        response = await self._client.audio.transcriptions.create(
            model=self._model,
            file=(filename, audio_bytes),
        )
        return response.text
