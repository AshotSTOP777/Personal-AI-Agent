from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.avito.scraper import extract_search_results, search_url
from app.browser.session import browser_session, detect_protection
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class AvitoSearchArgs(BaseModel):
    query: str = Field(description="Поисковый запрос для Avito")
    limit: int = Field(default=10, ge=1, le=10, description="Максимум объявлений (не больше 10)")


class AvitoSearchTool(Tool):
    name = "avito_search"
    description = (
        "Ищет объявления на Avito через реальный браузер (Playwright, сохранённая сессия). "
        "Возвращает до 10 уникальных объявлений (title, price, url) в JSON. "
        "Используй вместо fetch_page/web_search для Avito."
    )
    args_schema = AvitoSearchArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = AvitoSearchArgs.model_validate(kwargs)

        async def _search(page):
            await page.goto(search_url(args.query), timeout=browser_session.timeout_ms)
            body_text = await page.inner_text("body")
            warning = detect_protection(body_text)
            if warning:
                return warning
            results = await extract_search_results(page, limit=args.limit)
            if not results:
                return "Объявлений не найдено."
            return json.dumps(results, ensure_ascii=False)

        try:
            return await browser_session.run_exclusive(_search)
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось выполнить поиск на Avito: {exc}"
