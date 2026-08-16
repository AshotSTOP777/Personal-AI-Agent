from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.email.factory import build_email_provider
from app.email.gmail_provider import GmailApiProvider
from app.email.provider import EmailProvider


def _make_provider() -> GmailApiProvider:
    return GmailApiProvider(
        client_id="client-id", client_secret="client-secret", refresh_token="refresh-token", address="me@gmail.com"
    )


def _fake_response(json_data: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def test_get_access_token_calls_oauth_endpoint_and_caches():
    provider = _make_provider()
    token_response = _fake_response({"access_token": "token-123", "expires_in": 3600})

    with patch("app.email.gmail_provider.httpx.post", return_value=token_response) as mock_post:
        token1 = provider._get_access_token()
        token2 = provider._get_access_token()  # из кэша, без нового запроса

    assert token1 == "token-123"
    assert token2 == "token-123"
    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == "https://oauth2.googleapis.com/token"
    assert mock_post.call_args.kwargs["data"]["refresh_token"] == "refresh-token"


def test_send_posts_base64_message_with_bearer_token():
    provider = _make_provider()
    token_response = _fake_response({"access_token": "token-123", "expires_in": 3600})
    send_response = _fake_response({"id": "msg1"})

    with patch("app.email.gmail_provider.httpx.post", side_effect=[token_response, send_response]) as mock_post:
        provider.send("friend@example.com", "Привет", "Текст письма")

    send_call = mock_post.call_args_list[1]
    assert send_call.args[0] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    assert send_call.kwargs["headers"]["Authorization"] == "Bearer token-123"
    assert "raw" in send_call.kwargs["json"]


def test_read_recent_lists_and_summarizes_messages():
    provider = _make_provider()
    token_response = _fake_response({"access_token": "token-123", "expires_in": 3600})
    list_response = _fake_response({"messages": [{"id": "m1"}]})
    detail_response = _fake_response(
        {
            "snippet": "Короткий текст письма",
            "payload": {"headers": [
                {"name": "From", "value": "friend@example.com"},
                {"name": "Subject", "value": "Привет"},
                {"name": "Date", "value": "Mon, 1 Jan 2026 10:00:00 +0000"},
            ]},
        }
    )

    with patch("app.email.gmail_provider.httpx.post", return_value=token_response):
        with patch("app.email.gmail_provider.httpx.get", side_effect=[list_response, detail_response]) as mock_get:
            messages = provider.read_recent(limit=5)

    assert mock_get.call_args_list[0].kwargs["params"]["maxResults"] == 5
    assert messages == [
        {"from": "friend@example.com", "subject": "Привет", "date": "Mon, 1 Jan 2026 10:00:00 +0000", "snippet": "Короткий текст письма"}
    ]


def test_search_passes_query_param():
    provider = _make_provider()
    token_response = _fake_response({"access_token": "token-123", "expires_in": 3600})
    list_response = _fake_response({"messages": []})

    with patch("app.email.gmail_provider.httpx.post", return_value=token_response):
        with patch("app.email.gmail_provider.httpx.get", return_value=list_response) as mock_get:
            result = provider.search("invoice", limit=3)

    assert result == []
    assert mock_get.call_args.kwargs["params"]["q"] == "invoice"
    assert mock_get.call_args.kwargs["params"]["maxResults"] == 3


def test_factory_prefers_gmail_api_when_configured():
    settings = Settings(
        gmail_client_id="id", gmail_client_secret="secret", gmail_refresh_token="token", gmail_address="me@gmail.com",
        email_address="me@example.com", email_password="pw", smtp_host="smtp.example.com", imap_host="imap.example.com",
    )
    provider = build_email_provider(settings)
    assert isinstance(provider, GmailApiProvider)


def test_factory_falls_back_to_smtp_when_gmail_not_configured():
    settings = Settings(
        email_address="me@example.com", email_password="pw", smtp_host="smtp.example.com", imap_host="imap.example.com",
    )
    provider = build_email_provider(settings)
    assert isinstance(provider, EmailProvider)


def test_factory_returns_none_when_nothing_configured():
    settings = Settings()
    assert build_email_provider(settings) is None


def test_email_send_permission_uses_gmail_address(monkeypatch):
    from app.tools.email_send import EmailSendTool
    from app.tools.permissions import PermissionLevel

    monkeypatch.setattr("app.tools.email_send.settings.gmail_address", "me@gmail.com")
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "")
    tool = EmailSendTool()

    assert tool.permission_for({"to": "me@gmail.com"}) == PermissionLevel.SAFE
    assert tool.permission_for({"to": "other@example.com"}) == PermissionLevel.CONFIRM
