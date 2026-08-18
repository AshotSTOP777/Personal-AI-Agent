from __future__ import annotations

from pydantic import BaseModel, Field


class AvitoListing(BaseModel):
    title: str = ""
    price: str = ""
    url: str


class AvitoMessageItem(BaseModel):
    url: str = Field(description="URL объявления")
    message: str = Field(description="Готовый текст сообщения продавцу")
