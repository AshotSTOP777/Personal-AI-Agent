from __future__ import annotations

from urllib.parse import quote

SEARCH_URL_TEMPLATE = "https://www.avito.ru/rossiya?q={query}"
PROFILE_URL = "https://www.avito.ru/profile"
_LOGIN_URL_MARKERS = ("login", "signin")

_SEARCH_ITEMS_JS = """
(nodes) => nodes.map(n => {
    const titleEl = n.querySelector("[itemprop='name']") || n.querySelector("[data-marker='item-title']");
    const priceEl = n.querySelector("[itemprop='price']") || n.querySelector("[data-marker='item-price']");
    const linkEl = n.querySelector("a[data-marker='item-title']") || n.querySelector('a');
    return {
        title: titleEl ? titleEl.textContent.trim() : '',
        price: priceEl ? (priceEl.getAttribute('content') || priceEl.textContent.trim()) : '',
        url: linkEl ? linkEl.href : '',
    };
})
"""


def search_url(query: str) -> str:
    return SEARCH_URL_TEMPLATE.format(query=quote(query))


async def extract_search_results(page, limit: int = 10) -> list[dict]:
    """Извлекает объявления с текущей открытой страницы поиска Avito.
    Дедуплицирует по URL и ограничивает результат limit штук."""
    raw_items = await page.eval_on_selector_all("[data-marker='item']", _SEARCH_ITEMS_JS)

    seen: set[str] = set()
    unique: list[dict] = []
    for item in raw_items:
        url = (item or {}).get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append({"title": item.get("title", ""), "price": item.get("price", ""), "url": url})
        if len(unique) >= limit:
            break
    return unique


async def _text_or_empty(page, selector: str) -> str:
    try:
        el = await page.query_selector(selector)
        if el is None:
            return ""
        text = await el.text_content()
        return (text or "").strip()
    except Exception:  # noqa: BLE001
        return ""


async def extract_listing_details(page) -> dict:
    title = await _text_or_empty(page, "[data-marker='item-view/title-info'], h1")
    price = await _text_or_empty(page, "[data-marker='item-view/item-price'], [itemprop='price']")
    description = await _text_or_empty(
        page, "[data-marker='item-view/item-description'], [itemprop='description']"
    )
    return {"title": title, "price": price, "description": description, "url": page.url}


async def is_logged_in(page, timeout_ms: int = 15000) -> bool:
    """Открывает /profile сохранённой сессией и определяет, авторизован ли аккаунт."""
    await page.goto(PROFILE_URL, timeout=timeout_ms)
    url = (page.url or "").lower()
    if any(marker in url for marker in _LOGIN_URL_MARKERS):
        return False
    text = (await page.inner_text("body")).lower()
    if "войти" in text and "выйти" not in text and "личные данные" not in text:
        return False
    return True
