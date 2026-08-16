from __future__ import annotations

import base64
import time
from email.mime.text import MIMEText

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_SNIPPET_CHARS = 500


class GmailApiProvider:
    """Email-провайдер через Gmail REST API (HTTPS) с OAuth2 refresh token — замена
    прямому SMTP/IMAP. Методы синхронные, как у EmailProvider (SMTP/IMAP fallback),
    чтобы инструменты email_send/email_read_recent/email_search работали без изменений
    (вызывающий код сам выполняет их в потоке через asyncio.to_thread)."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, address: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._address = address
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token
        response = httpx.post(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 3600)
        return self._access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_access_token()}"}

    def send(self, to: str, subject: str, body: str) -> None:
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = self._address
        message["To"] = to
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        response = httpx.post(
            f"{API_BASE}/messages/send", headers=self._headers(), json={"raw": raw}, timeout=15
        )
        response.raise_for_status()

    def read_recent(self, limit: int = 5) -> list[dict[str, str]]:
        return [self._fetch_summary(msg_id) for msg_id in self._list_message_ids(limit=limit)]

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        return [self._fetch_summary(msg_id) for msg_id in self._list_message_ids(limit=limit, query=query)]

    def _list_message_ids(self, limit: int, query: str | None = None) -> list[str]:
        params: dict[str, object] = {"maxResults": limit}
        if query:
            params["q"] = query
        response = httpx.get(f"{API_BASE}/messages", headers=self._headers(), params=params, timeout=15)
        response.raise_for_status()
        return [m["id"] for m in response.json().get("messages", [])]

    def _fetch_summary(self, message_id: str) -> dict[str, str]:
        params = {"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]}
        response = httpx.get(
            f"{API_BASE}/messages/{message_id}", headers=self._headers(), params=params, timeout=15
        )
        response.raise_for_status()
        data = response.json()
        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
        snippet = data.get("snippet", "")
        if len(snippet) > MAX_SNIPPET_CHARS:
            snippet = snippet[:MAX_SNIPPET_CHARS].rstrip() + "…"
        return {
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": snippet,
        }
