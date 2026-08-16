from __future__ import annotations

from app.ai.base import AIProvider
from app.config import Settings


def build_provider(settings: Settings) -> AIProvider:
    """Выбирает AI-провайдера по settings.ai_provider, не завязывая остальной код на конкретный SDK."""
    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY не задан")
        from app.ai.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)

    if settings.ai_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY не задан")
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    if settings.ai_provider == "openrouter":
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY не задан")
        from app.ai.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider(api_key=settings.openrouter_api_key, model=settings.openrouter_model)

    raise RuntimeError(f"Неизвестный AI_PROVIDER: {settings.ai_provider!r}")
