from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.avito.scraper import extract_listing_details
from app.browser.session import browser_session, detect_protection
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class AvitoReadListingArgs(BaseModel):
    url: str = Field(description="URL конкретного объявления Avito")


class AvitoReadListingTool(Tool):
    name = "avito_read_listing"
    description = "Открывает конкретное объявление Avito и читает цену, название, описание."
    args_schema = AvitoReadListingArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = AvitoReadListingArgs.model_validate(kwargs)

        async def _read(page):
            await page.goto(args.url, timeout=browser_session.timeout_ms)
            body_text = await page.inner_text("body")
            warning = detect_protection(body_text)
            if warning:
                return warning
            details = await extract_listing_details(page)
            return json.dumps(details, ensure_ascii=False)

        try:
            return await browser_session.run_exclusive(_read)
        except Exception as exc:  # noqa: BLE001
            return f"Не удалось открыть объявление: {exc}"
