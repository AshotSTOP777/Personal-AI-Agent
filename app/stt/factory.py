from __future__ import annotations

from app.config import Settings
from app.logging_setup import get_logger
from app.stt.base import STTProvider

logger = get_logger(__name__)


def build_stt_provider(settings: Settings) -> STTProvider | None:
    """Выбирает STT-провайдера по settings.stt_provider. В отличие от AI-провайдера,
    никогда не поднимает исключение — распознавание голоса опционально и не должно
    мешать запуску бота, если не настроено."""
    if settings.stt_provider == "groq":
        if not settings.groq_api_key:
            logger.warning("stt_not_configured", provider="groq", reason="missing GROQ_API_KEY")
            return None
        from app.stt.groq_provider import GroqWhisperProvider

        return GroqWhisperProvider(api_key=settings.groq_api_key, model=settings.stt_model)

    if settings.stt_provider:
        logger.warning("stt_unknown_provider", provider=settings.stt_provider)
    return None
