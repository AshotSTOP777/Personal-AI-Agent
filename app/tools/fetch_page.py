from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, Field

from app.logging_setup import get_logger
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel
from app.tools.url_safety import UnsafeUrlError, assert_url_allowed

logger = get_logger(__name__)

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

MAX_CONTENT_CHARS = 4000


def _extract_main_text(html: str, limit: int) -> str:
    html = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", html)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


class FetchPageArgs(BaseModel):
    url: str = Field(description="Полный URL страницы, включая http:// или https://")


class FetchPageTool(Tool):
    name = "fetch_page"
    description = (
        "Загружает статический HTML по URL и возвращает основной текст. "
        "Не исполняет JavaScript. Не используй как основной инструмент для Avito, "
        "маркетплейсов, личных кабинетов, чатов, динамических цен и интерактивных страниц — "
        "для них используй browser_open/browser_read."
    )
    args_schema = FetchPageArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = FetchPageArgs.model_validate(kwargs)

        try:
            assert_url_allowed(args.url)
        except UnsafeUrlError as exc:
            return f"Не удалось загрузить страницу: {exc}"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                response = await client.get(
                    args.url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; PersonalAIAgent/1.0)"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("fetch_page_failed", url=args.url, error=str(exc))
            return "Не удалось загрузить страницу. Проверь ссылку или повтори позже."

        text = _extract_main_text(response.text, MAX_CONTENT_CHARS)
        if not text:
            return f"{args.url}\n\nСтраница загружена, но не удалось извлечь текст."
        return f"{args.url}\n\n{text}"
