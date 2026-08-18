from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.browser.session import browser_session
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel

_EXTRACT_JS = "(nodes) => nodes.map(n => (n.innerText || n.textContent || '').trim()).filter(Boolean)"


class SiteExtractArgs(BaseModel):
    selector: str = Field(description="CSS-селектор элементов для извлечения (например, .product-card)")
    limit: int = Field(default=20, ge=1, le=50)


class SiteExtractTool(Tool):
    name = "site_extract"
    description = (
        "Извлекает текст всех элементов текущей страницы по CSS-селектору (карточки товаров, "
        "строки таблицы, список результатов и т.п.). Универсальный инструмент для любого сайта "
        "(не только Avito) — используй после browser_open для сбора структурированных данных."
    )
    args_schema = SiteExtractArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = SiteExtractArgs.model_validate(kwargs)
        try:
            page = await browser_session.get_page()
            items = await page.eval_on_selector_all(args.selector, _EXTRACT_JS)
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось извлечь данные: {exc}"

        items = list(items)[: args.limit]
        if not items:
            return "По этому селектору ничего не найдено."
        return json.dumps(items, ensure_ascii=False)
