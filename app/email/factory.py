from __future__ import annotations

from app.config import Settings
from app.email.provider import EmailProvider


def build_email_provider(settings: Settings) -> EmailProvider | None:
    """Никогда не поднимает исключение — почта опциональна и не должна мешать запуску бота."""
    if not (settings.email_address and settings.email_password and settings.smtp_host and settings.imap_host):
        return None
    return EmailProvider(
        address=settings.email_address,
        password=settings.email_password,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        imap_host=settings.imap_host,
        imap_port=settings.imap_port,
    )
