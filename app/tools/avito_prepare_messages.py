from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.avito.pricing import draft_message
from app.avito.schemas import AvitoListing
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel


class AvitoPrepareMessagesArgs(BaseModel):
    listings: list[AvitoListing] = Field(description="Объявления (title, price, url), обычно из avito_search")
    discount_percent: float | None = Field(
        default=None, description="Если нужен торг — на сколько процентов ниже цены предложить"
    )


class AvitoPrepareMessagesTool(Tool):
    name = "avito_prepare_messages"
    description = (
        "Готовит персональные сообщения продавцам по списку объявлений (ничего не отправляет). "
        "Если задан discount_percent — рассчитывает предложение как цена * (1 - discount_percent/100). "
        "Результат (JSON-список url/message) передай в avito_send_messages для отправки."
    )
    args_schema = AvitoPrepareMessagesArgs
    permission = PermissionLevel.SAFE

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = AvitoPrepareMessagesArgs.model_validate(kwargs)
        prepared = [
            {
                "url": listing.url,
                "message": draft_message(listing.title, listing.price, args.discount_percent),
            }
            for listing in args.listings
        ]
        return json.dumps(prepared, ensure_ascii=False)
