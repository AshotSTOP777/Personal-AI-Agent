from __future__ import annotations

import re
from pathlib import Path

from app.config import settings

MAX_READ_CHARS = 4000

_PROTECTION_KEYWORDS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "verify you're human",
    "confirm you're not a robot",
    "two-factor",
    "2fa",
    "one-time code",
    "одноразовый код",
    "подтвердите, что вы не робот",
)


def detect_protection(text: str) -> str | None:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _PROTECTION_KEYWORDS):
        return (
            "⚠️ Обнаружена CAPTCHA / 2FA / антибот-защита. Автоматические действия остановлены — "
            "нужно, чтобы владелец прошёл эту проверку вручную."
        )
    return None


class BrowserSession:
    """Один persistent Chromium context (Playwright) на процесс.

    Cookies, local storage и авторизация сохраняются в profile_dir и переживают
    перезапуск процесса. Это позволяет один раз вручную войти, например, в Avito,
    после чего работать в headless-режиме с той же сессией.

    profile_dir содержит чувствительные данные авторизации и не должен попадать в git.
    """

    def __init__(
        self,
        timeout_ms: int = 15000,
        profile_dir: str = ".browser-profile",
        headless: bool = True,
    ) -> None:
        self._timeout_ms = timeout_ms
        self._profile_dir = Path(profile_dir).expanduser()
        self._headless = headless
        self._playwright = None
        self._context = None
        self._page = None

    async def _ensure_page(self):
        if self._page is not None and not self._page.is_closed():
            return self._page
        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=self._headless,
        )
        page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        page.set_default_timeout(self._timeout_ms)
        self._page = page
        return self._page

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    async def get_page(self):
        """Даёт прямой доступ к Playwright Page для специализированных инструментов
        (например, скрапинг Avito), которым нужно больше, чем базовые open/read/click."""
        return await self._ensure_page()

    async def open(self, url: str) -> str:
        page = await self._ensure_page()
        await page.goto(url, timeout=self._timeout_ms)
        title = await page.title()
        return f"Открыл {page.url} («{title}»)."

    async def read(self, max_chars: int = MAX_READ_CHARS) -> str:
        page = await self._ensure_page()
        raw_text = await page.inner_text("body")
        text = re.sub(r"\s+", " ", raw_text).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "…"
        warning = detect_protection(text)
        return f"{warning}\n\n{text}" if warning else text

    async def click(self, selector: str) -> str:
        page = await self._ensure_page()
        await page.click(selector, timeout=self._timeout_ms)
        return f"Кликнул по элементу '{selector}'. Текущий URL: {page.url}"

    async def type(self, selector: str, text: str) -> str:
        page = await self._ensure_page()
        await page.fill(selector, text, timeout=self._timeout_ms)
        return f"Ввёл текст в поле '{selector}'."

    async def submit(self, selector: str | None = None) -> str:
        page = await self._ensure_page()
        if selector:
            await page.click(selector, timeout=self._timeout_ms)
        else:
            await page.keyboard.press("Enter")
        return f"Отправил форму. Текущий URL: {page.url}"

    async def current_url(self) -> str:
        page = await self._ensure_page()
        return page.url

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._playwright = None


browser_session = BrowserSession(
    timeout_ms=settings.browser_timeout_ms,
    profile_dir=settings.browser_profile_dir,
    headless=settings.browser_headless,
)
