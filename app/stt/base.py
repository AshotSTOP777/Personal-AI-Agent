from __future__ import annotations

from abc import ABC, abstractmethod


class STTProvider(ABC):
    """Абстракция над speech-to-text бэкендом. Позволяет заменить провайдера
    (сейчас Groq Whisper), не меняя bot-слой."""

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        """Распознаёт речь в аудио и возвращает текст."""
        raise NotImplementedError
