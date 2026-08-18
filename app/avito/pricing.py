from __future__ import annotations

import re


def parse_price(raw: str) -> int | None:
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else None


def compute_offer(price: int, discount_percent: float) -> int:
    return max(round(price * (1 - discount_percent / 100)), 0)


def draft_message(title: str, price_text: str, discount_percent: float | None = None) -> str:
    """Готовит короткое персональное сообщение продавцу. Если задан торг — считает
    предложение как price * (1 - discount_percent / 100)."""
    if discount_percent:
        price = parse_price(price_text)
        if price:
            offer = compute_offer(price, discount_percent)
            return f"Здравствуйте! Интересует «{title}». Отдадите за {offer} руб.?"
    return f"Здравствуйте! Интересует «{title}». Актуально ли объявление?"
