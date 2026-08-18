from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from app.config import settings

MAX_READ_CHARS = 4000
CHROMIUM_INSTALL_TIMEOUT_SECONDS = 300

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


async def _install_chromium() -> None:
    """Ставит Chromium без блокировки event loop (в отличие от subprocess.run)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "playwright", "install", "chromium"
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=CHROMIUM_INSTALL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise RuntimeError("Установка Chromium не уложилась в отведённое время.") from exc
    if proc.returncode != 0:
        raise RuntimeError("playwright install chromium завершился с ошибкой.")


class BrowserSession:
    """Один persistent Chromium context (Playwright) на процесс.

    Cookies, local storage и авторизация сохраняются в profile_dir и переживают
    перезапуск процесса. Это позволяет один раз вручную войти, например, в Avito,
    после чего работать в headless-режиме с той же сессией.

    Одна страница используется всеми потребителями (интерактивный чат и JobWorker),
    поэтому все операции сериализуются через asyncio.Lock — конкурентные запросы не
    уводят страницу друг у друга из-под ног, а просто выполняются по очереди.

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
        self._lock = asyncio.Lock()

    async def _page_is_usable(self) -> bool:
        if self._page is None:
            return False
        try:
            # is_closed() может кинуть, если браузер уже упал/закрыт пользователем вручную
            return not self._page.is_closed()
        except Exception:  # noqa: BLE001
            return False

    async def _ensure_page(self, headless: bool | None = None):
        if await self._page_is_usable():
            return self._page

        # предыдущий context мог упасть/быть закрыт вручную — сбрасываем состояние перед релончем
        await self._close_locked()

        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        self._profile_dir.mkdir(parents=True, exist_ok=True)
        launch_headless = self._headless if headless is None else headless
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self._profile_dir),
                headless=launch_headless,
            )
        except Exception as exc:  # noqa: BLE001
            if "Executable doesn't exist" not in str(exc):
                raise
            await _install_chromium()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self._profile_dir),
                headless=launch_headless,
            )
        page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        page.set_default_timeout(self._timeout_ms)
        self._page = page
        return self._page

    async def reopen_visible(self) -> None:
        """Закрывает текущий (headless) context и открывает видимое окно Chromium с тем
        же persistent-профилем — используется для ручного входа/CAPTCHA/2FA по требованию."""
        async with self._lock:
            await self._close_locked()
            await self._ensure_page(headless=False)

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    async def get_page(self):
        """Даёт прямой доступ к Playwright Page для специализированных инструментов
        (например, скрапинг Avito). ВНИМАНИЕ: не сериализуется локом сам по себе — если
        нужно несколько операций подряд атомарно (goto -> extract, goto -> click -> fill),
        используй run_exclusive, иначе конкурентный запрос может перехватить страницу
        между вызовами."""
        return await self._ensure_page()

    async def run_exclusive(self, action):
        """Выполняет `action(page)` под общим локом браузера — гарантирует, что между
        несколькими последовательными действиями (например, goto -> click -> fill в
        одном tool) никто другой не переключит страницу на другой URL."""
        async with self._lock:
            page = await self._ensure_page()
            return await action(page)

    async def open(self, url: str) -> str:
        async with self._lock:
            page = await self._ensure_page()
            await page.goto(url, timeout=self._timeout_ms)
            title = await page.title()
            return f"Открыл {page.url} («{title}»)."

    async def read(self, max_chars: int = MAX_READ_CHARS) -> str:
        async with self._lock:
            page = await self._ensure_page()
            raw_text = await page.inner_text("body")
        text = re.sub(r"\s+", " ", raw_text).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "…"
        warning = detect_protection(text)
        return f"{warning}\n\n{text}" if warning else text

    async def click(self, selector: str) -> str:
        async with self._lock:
            page = await self._ensure_page()
            await page.click(selector, timeout=self._timeout_ms)
            return f"Кликнул по элементу '{selector}'. Текущий URL: {page.url}"

    async def type(self, selector: str, text: str) -> str:
        async with self._lock:
            page = await self._ensure_page()
            await page.fill(selector, text, timeout=self._timeout_ms)
            return f"Ввёл текст в поле '{selector}'."

    async def submit(self, selector: str | None = None) -> str:
        async with self._lock:
            page = await self._ensure_page()
            if selector:
                await page.click(selector, timeout=self._timeout_ms)
            else:
                await page.keyboard.press("Enter")
            return f"Отправил форму. Текущий URL: {page.url}"

    async def current_url(self) -> str:
        async with self._lock:
            page = await self._ensure_page()
            return page.url

    async def _close_locked(self) -> None:
        """Закрытие без повторного захвата self._lock — вызывается из мест, которые уже
        держат лок (_ensure_page, reopen_visible)."""
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
        self._page = None
        self._context = None
        self._playwright = None

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()


browser_session = BrowserSession(
    timeout_ms=settings.browser_timeout_ms,
    profile_dir=settings.browser_profile_dir,
    headless=settings.browser_headless,
)
