from __future__ import annotations

from openai import AsyncOpenAI

from app.stt.base import STTProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterSTTProvider(STTProvider):
    """Speech-to-text через OpenRouter (https://openrouter.ai/api/v1/audio/transcriptions),
    OpenAI-совместимый API. Использует тот же OPENROUTER_API_KEY, что и OpenRouterProvider."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
        self._model = model

    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        response = await self._client.audio.transcriptions.create(
            model=self._model,
            file=(filename, audio_bytes),
        )
        return response.text
