from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, Field

from app.logging_setup import get_logger
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel

logger = get_logger(__name__)

_RESULT_RE = re.compile(
    r'result__a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?result__snippet[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


class WebSearchArgs(BaseModel):
    query: str = Field(description="Поисковый запрос")
    max_results: int = Field(default=5, ge=1, le=10, description="Максимум результатов")


class WebSearchTool(Tool):
    name = "web_search"
    description = "Ищет актуальную информацию в интернете и возвращает краткие результаты с ссылками."
    args_schema = WebSearchArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = WebSearchArgs.model_validate(kwargs)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": args.query},
                    headers={"User-Agent": "Mozilla/5.0 (compatible; PersonalAIAgent/1.0)"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("web_search_failed", error=str(exc))
            return "Не удалось выполнить поиск в интернете. Попробуй переформулировать запрос или повтори позже."

        matches = _RESULT_RE.finditer(response.text)
        results = []
        for match in matches:
            title = _strip_tags(match.group("title"))
            snippet = _strip_tags(match.group("snippet"))
            url = match.group("url")
            results.append(f"- {title}\n  {url}\n  {snippet}")
            if len(results) >= args.max_results:
                break

        if not results:
            return "По запросу ничего не найдено."
        return "\n".join(results)
