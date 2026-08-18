from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = {"localhost"}


class UnsafeUrlError(ValueError):
    pass


def assert_url_allowed(url: str) -> None:
    """SSRF guard для LLM-управляемых browsing tools (fetch_page, browser_open): только
    http/https, никакого localhost/приватных/loopback адресов. Не применяется к
    доверенным детерминированным командам (например /avito_login), которые открывают
    фиксированные внешние URL напрямую через BrowserSession, минуя этот tool-слой."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("разрешены только http/https ссылки.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise UnsafeUrlError("некорректный URL.")
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise UnsafeUrlError("доступ к localhost запрещён.")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return  # обычное доменное имя, не IP-литерал

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        raise UnsafeUrlError("доступ к приватным/локальным адресам запрещён.")
