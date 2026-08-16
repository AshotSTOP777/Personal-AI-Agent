from __future__ import annotations

import pytest

from app.tools.base import ToolContext
from app.tools.fetch_page import FetchPageTool


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/",
        "http://127.0.0.1/admin",
        "http://192.168.1.10/",
        "http://10.0.0.5/",
        "http://[::1]/",
        "ftp://example.com/file",
    ],
)
async def test_fetch_page_blocks_unsafe_urls(db_session, url):
    tool = FetchPageTool()
    ctx = ToolContext(user_id=1, session=db_session)

    result = await tool.run(ctx, url=url)

    assert result.startswith("Не удалось загрузить страницу:")


@pytest.mark.asyncio
async def test_fetch_page_allows_public_https_url(db_session, monkeypatch):
    import httpx

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, text="<html><body><p>Привет мир</p></body></html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tool = FetchPageTool()
    ctx = ToolContext(user_id=1, session=db_session)

    result = await tool.run(ctx, url="https://example.com/article")

    assert "https://example.com/article" in result
    assert "Привет мир" in result
