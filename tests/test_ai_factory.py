from __future__ import annotations

import pytest

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.factory import build_provider
from app.ai.gemini_provider import GeminiProvider
from app.config import Settings


def test_build_provider_gemini_does_not_require_anthropic_key():
    settings = Settings(ai_provider="gemini", gemini_api_key="fake-gemini-key", anthropic_api_key="")
    provider = build_provider(settings)
    assert isinstance(provider, GeminiProvider)


def test_build_provider_anthropic_default():
    settings = Settings(ai_provider="anthropic", anthropic_api_key="fake-anthropic-key")
    provider = build_provider(settings)
    assert isinstance(provider, AnthropicProvider)


def test_build_provider_gemini_without_key_raises():
    settings = Settings(ai_provider="gemini", gemini_api_key="")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        build_provider(settings)


def test_build_provider_anthropic_without_key_raises():
    settings = Settings(ai_provider="anthropic", anthropic_api_key="")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_provider(settings)


def test_build_provider_unknown_raises():
    settings = Settings(ai_provider="unknown")
    with pytest.raises(RuntimeError, match="AI_PROVIDER"):
        build_provider(settings)
