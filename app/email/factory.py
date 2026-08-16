from __future__ import annotations

from typing import Union

from app.config import Settings
from app.email.provider import EmailProvider

EmailProviderLike = Union[EmailProvider, "GmailApiProvider"]  # noqa: F821


def build_email_provider(settings: Settings) -> EmailProviderLike | None:
    """Никогда не поднимает исключение — почта опциональна и не должна мешать запуску бота.
    Если настроен Gmail API (OAuth2, HTTPS) — используется он; иначе fallback на SMTP/IMAP."""
    if settings.gmail_client_id and settings.gmail_client_secret and settings.gmail_refresh_token and settings.gmail_address:
        from app.email.gmail_provider import GmailApiProvider

        return GmailApiProvider(
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            refresh_token=settings.gmail_refresh_token,
            address=settings.gmail_address,
        )

    if settings.email_address and settings.email_password and settings.smtp_host and settings.imap_host:
        return EmailProvider(
            address=settings.email_address,
            password=settings.email_password,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            imap_host=settings.imap_host,
            imap_port=settings.imap_port,
        )

    return None
