from __future__ import annotations

import email as email_lib
import imaplib
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText

MAX_SNIPPET_CHARS = 500


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded += text.decode(charset or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def _extract_body(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""
    payload = message.get_payload(decode=True) or b""
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _summarize(raw: bytes) -> dict[str, str]:
    message = email_lib.message_from_bytes(raw)
    body = _extract_body(message).strip()
    if len(body) > MAX_SNIPPET_CHARS:
        body = body[:MAX_SNIPPET_CHARS].rstrip() + "…"
    return {
        "from": _decode(message.get("From")),
        "subject": _decode(message.get("Subject")),
        "date": message.get("Date") or "",
        "snippet": body,
    }


class EmailProvider:
    """Простой email-провайдер: отправка через SMTP, чтение через IMAP.
    Методы синхронные (smtplib/imaplib) — вызывающий код должен выполнять их
    в отдельном потоке (asyncio.to_thread), чтобы не блокировать event loop."""

    def __init__(
        self,
        address: str,
        password: str,
        smtp_host: str,
        smtp_port: int,
        imap_host: str,
        imap_port: int,
    ) -> None:
        self._address = address
        self._password = password
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._imap_host = imap_host
        self._imap_port = imap_port

    def send(self, to: str, subject: str, body: str) -> None:
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = self._address
        message["To"] = to
        with smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=15) as server:
            server.login(self._address, self._password)
            server.send_message(message)

    def read_recent(self, limit: int = 5) -> list[dict[str, str]]:
        with imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=15) as server:
            server.login(self._address, self._password)
            server.select("INBOX", readonly=True)
            status, data = server.search(None, "ALL")
            if status != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()[-limit:]
            return self._fetch_all(server, reversed(ids))

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        with imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=15) as server:
            server.login(self._address, self._password)
            server.select("INBOX", readonly=True)
            safe_query = query.replace('"', "'")
            status, data = server.search(None, f'(OR SUBJECT "{safe_query}" FROM "{safe_query}")')
            if status != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()[-limit:]
            return self._fetch_all(server, reversed(ids))

    @staticmethod
    def _fetch_all(server: imaplib.IMAP4_SSL, ids) -> list[dict[str, str]]:
        messages = []
        for msg_id in ids:
            status, msg_data = server.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            messages.append(_summarize(msg_data[0][1]))
        return messages
