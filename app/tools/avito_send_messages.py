from __future__ import annotations

from pydantic import BaseModel, Field

from app.avito.schemas import AvitoMessageItem
from app.avito.scraper import is_logged_in
from app.browser.session import browser_session, detect_protection
from app.tools.base import Tool, ToolContext
from app.tools.permissions import PermissionLevel

MAX_MESSAGES = 10

_WRITE_BUTTON_SELECTORS = ["[data-marker='messenger-button']", "text=Написать"]
_MESSAGE_INPUT_SELECTORS = ["[data-marker='messenger-input']", "textarea"]
_SEND_BUTTON_SELECTORS = ["[data-marker='messenger-send-button']", "button[type='submit']"]


class ProtectionDetected(Exception):
    pass


async def _try_selectors(action, selectors: list[str], timeout_ms: int) -> bool:
    for selector in selectors:
        try:
            await action(selector, timeout_ms)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _dedupe_by_url(items: list[AvitoMessageItem]) -> list[AvitoMessageItem]:
    seen: set[str] = set()
    unique: list[AvitoMessageItem] = []
    for item in items:
        if item.url in seen:
            continue
        seen.add(item.url)
        unique.append(item)
    return unique


async def _send_one(page, url: str, message: str, timeout_ms: int) -> str:
    await page.goto(url, timeout=timeout_ms)
    body_text = await page.inner_text("body")
    if detect_protection(body_text):
        raise ProtectionDetected(url)

    clicked_write = await _try_selectors(
        lambda sel, t: page.click(sel, timeout=t), _WRITE_BUTTON_SELECTORS, timeout_ms
    )
    if not clicked_write:
        return "failed"

    filled = await _try_selectors(
        lambda sel, t: page.fill(sel, message, timeout=t), _MESSAGE_INPUT_SELECTORS, timeout_ms
    )
    if not filled:
        return "failed"

    clicked_send = await _try_selectors(
        lambda sel, t: page.click(sel, timeout=t), _SEND_BUTTON_SELECTORS, timeout_ms
    )
    if not clicked_send:
        return "failed"

    # Клик по кнопке ещё не значит, что письмо реально ушло — проверяем состояние UI:
    # поле ввода должно очиститься/скрыться после успешной отправки.
    try:
        input_value = await page.eval_on_selector(
            _MESSAGE_INPUT_SELECTORS[0], "el => el && 'value' in el ? el.value : (el ? el.innerText : '')"
        )
        if input_value and input_value.strip() == message.strip():
            return "uncertain"  # поле не очистилось — отправка не подтверждена
    except Exception:  # noqa: BLE001
        pass
    return "sent"


class AvitoSendMessagesArgs(BaseModel):
    messages: list[AvitoMessageItem] = Field(
        max_length=MAX_MESSAGES, description="Готовый список сообщений (обычно из avito_prepare_messages), максимум 10"
    )


class AvitoSendMessagesTool(Tool):
    name = "avito_send_messages"
    description = (
        "Отправляет заранее подготовленные сообщения продавцам на Avito (максимум 10 за раз, "
        "дубликаты по url отбрасываются). Необратимое действие — требует подтверждения владельца. "
        "При CAPTCHA/2FA немедленно останавливается. Не используй для массовой рассылки без "
        "подготовленного списка."
    )
    args_schema = AvitoSendMessagesArgs
    permission = PermissionLevel.CONFIRM

    async def run(self, ctx: ToolContext, **kwargs) -> str:
        args = AvitoSendMessagesArgs.model_validate(kwargs)
        messages = _dedupe_by_url(args.messages)
        timeout_ms = browser_session.timeout_ms

        async def _check_login(page):
            return await is_logged_in(page, timeout_ms=timeout_ms)

        if not await browser_session.run_exclusive(_check_login):
            await browser_session.reopen_visible()

            async def _open_login(page):
                await page.goto("https://www.avito.ru", timeout=timeout_ms)

            await browser_session.run_exclusive(_open_login)
            return (
                "Аккаунт Avito не авторизован. Открыл окно браузера — войди вручную "
                "(включая CAPTCHA/SMS/2FA при необходимости), затем повтори отправку."
            )

        async def _send_batch(page) -> str:
            results: list[str] = []
            stopped = False
            for item in messages:
                if stopped:
                    results.append(f"{item.url}: skipped")
                    continue
                try:
                    status = await _send_one(page, item.url, item.message, timeout_ms)
                    results.append(f"{item.url}: {status}")
                except ProtectionDetected:
                    results.append(f"{item.url}: skipped (CAPTCHA/2FA — нужна проверка владельца)")
                    stopped = True
                except Exception as exc:  # noqa: BLE001
                    results.append(f"{item.url}: failed ({exc})")
            return "\n".join(results)

        return await browser_session.run_exclusive(_send_batch)
