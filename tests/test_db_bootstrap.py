from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from app.db import bootstrap as db_bootstrap


def test_run_powershell_never_raises_on_bad_bytes(monkeypatch):
    bad = b"postgresql-x64-16\x98\x00"
    monkeypatch.setattr(
        db_bootstrap.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=bad)
    )
    output = db_bootstrap._run_powershell("whatever", timeout=5)
    assert "postgresql-x64-16" in output


def test_find_windows_pg_service_parses_ps_output(monkeypatch):
    monkeypatch.setattr(db_bootstrap, "_run_powershell", lambda script, timeout: "postgresql-x64-16")
    assert db_bootstrap._find_windows_pg_service() == "postgresql-x64-16"


def test_find_windows_pg_service_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(db_bootstrap, "_run_powershell", lambda script, timeout: "")
    assert db_bootstrap._find_windows_pg_service() is None


def test_find_windows_pg_service_is_language_independent(monkeypatch):
    """Использует CIM Name (внутренний, не локализованный), а не DisplayName из sc.exe."""
    calls: list[str] = []

    def fake_run(script: str, timeout: int) -> str:
        calls.append(script)
        return "postgresql-x64-17"

    monkeypatch.setattr(db_bootstrap, "_run_powershell", fake_run)
    result = db_bootstrap._find_windows_pg_service()

    assert result == "postgresql-x64-17"
    assert "Get-CimInstance" in calls[0]
    assert "DisplayName" not in calls[0]


def test_classify_credential_error_distinguishes_missing_role():
    role_error = Exception('role "ghost" does not exist')
    password_error = Exception("password authentication failed")

    assert "не существует" in db_bootstrap._classify_credential_error(role_error)
    assert "Неверный пароль" in db_bootstrap._classify_credential_error(password_error)


@pytest.mark.asyncio
async def test_ensure_postgres_ready_ok_when_reachable(monkeypatch):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    monkeypatch.setattr(db_bootstrap.asyncpg, "connect", AsyncMock(return_value=conn))

    result = await db_bootstrap.ensure_postgres_ready("postgresql+asyncpg://user:pw@localhost:5432/mydb")

    assert result == "OK"


@pytest.mark.asyncio
async def test_ensure_postgres_ready_reports_credential_error_without_service_check(monkeypatch):
    monkeypatch.setattr(
        db_bootstrap.asyncpg, "connect", AsyncMock(side_effect=asyncpg.InvalidPasswordError("bad password"))
    )
    find_service = MagicMock()
    monkeypatch.setattr(db_bootstrap, "_find_windows_pg_service", find_service)

    result = await db_bootstrap.ensure_postgres_ready("postgresql+asyncpg://user:wrong@localhost:5432/mydb")

    assert "Неверный пароль" in result
    find_service.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_postgres_ready_shows_winget_hint_only_when_service_missing(monkeypatch):
    monkeypatch.setattr(db_bootstrap.asyncpg, "connect", AsyncMock(side_effect=ConnectionRefusedError()))
    monkeypatch.setattr(db_bootstrap, "_is_local", lambda host: True)
    monkeypatch.setattr(db_bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(db_bootstrap, "_find_windows_pg_service", lambda: None)

    result = await db_bootstrap.ensure_postgres_ready("postgresql+asyncpg://user:pw@localhost:5432/mydb")

    assert result == db_bootstrap.WINGET_INSTALL_HINT


@pytest.mark.asyncio
async def test_ensure_postgres_ready_starts_stopped_service_and_retries(monkeypatch):
    connect_mock = AsyncMock(side_effect=[ConnectionRefusedError(), AsyncMock()])
    monkeypatch.setattr(db_bootstrap.asyncpg, "connect", connect_mock)
    monkeypatch.setattr(db_bootstrap, "_is_local", lambda host: True)
    monkeypatch.setattr(db_bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(db_bootstrap, "_find_windows_pg_service", lambda: "postgresql-x64-16")
    start_mock = MagicMock(return_value=True)
    monkeypatch.setattr(db_bootstrap, "_start_windows_service", start_mock)
    monkeypatch.setattr(db_bootstrap, "_ensure_database_exists", AsyncMock())

    result = await db_bootstrap.ensure_postgres_ready("postgresql+asyncpg://user:pw@localhost:5432/mydb")

    start_mock.assert_called_once_with("postgresql-x64-16")
    assert result == "OK"


@pytest.mark.asyncio
async def test_ensure_postgres_ready_service_wont_start_needs_admin(monkeypatch):
    monkeypatch.setattr(db_bootstrap.asyncpg, "connect", AsyncMock(side_effect=ConnectionRefusedError()))
    monkeypatch.setattr(db_bootstrap, "_is_local", lambda host: True)
    monkeypatch.setattr(db_bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(db_bootstrap, "_find_windows_pg_service", lambda: "postgresql-x64-16")
    monkeypatch.setattr(db_bootstrap, "_start_windows_service", lambda name: False)
    monkeypatch.setattr(db_bootstrap, "_is_elevated", lambda: False)

    result = await db_bootstrap.ensure_postgres_ready("postgresql+asyncpg://user:pw@localhost:5432/mydb")

    assert "postgresql-x64-16" in result
    assert "администратора" in result


@pytest.mark.asyncio
async def test_ensure_postgres_ready_service_wont_start_when_elevated_generic_message(monkeypatch):
    monkeypatch.setattr(db_bootstrap.asyncpg, "connect", AsyncMock(side_effect=ConnectionRefusedError()))
    monkeypatch.setattr(db_bootstrap, "_is_local", lambda host: True)
    monkeypatch.setattr(db_bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(db_bootstrap, "_find_windows_pg_service", lambda: "postgresql-x64-16")
    monkeypatch.setattr(db_bootstrap, "_start_windows_service", lambda name: False)
    monkeypatch.setattr(db_bootstrap, "_is_elevated", lambda: True)

    result = await db_bootstrap.ensure_postgres_ready("postgresql+asyncpg://user:pw@localhost:5432/mydb")

    assert "postgresql-x64-16" in result
    assert "net start" in result


@pytest.mark.asyncio
async def test_ensure_postgres_ready_running_service_with_placeholder_credentials(monkeypatch):
    """Регрессия: DATABASE_URL по умолчанию содержит user:password. Служба реально Running,
    но подключение всё равно рвётся (частый случай — несуществующая роль) с ошибкой, которую
    asyncpg не классифицирует как InvalidPassword/InvalidAuthorizationSpecification. Раньше
    это ошибочно репортилось как 'служба не запускается', хотя служба работает."""
    monkeypatch.setattr(
        db_bootstrap.asyncpg, "connect", AsyncMock(side_effect=asyncpg.ConnectionDoesNotExistError("closed"))
    )
    monkeypatch.setattr(db_bootstrap, "_is_local", lambda host: True)
    monkeypatch.setattr(db_bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(db_bootstrap, "_find_windows_pg_service", lambda: "postgresql-x64-16")
    monkeypatch.setattr(db_bootstrap, "_start_windows_service", lambda name: True)
    monkeypatch.setattr(db_bootstrap.asyncio, "sleep", AsyncMock())

    result = await db_bootstrap.ensure_postgres_ready("postgresql+asyncpg://user:password@localhost:5432/mydb")

    assert "запущена" in result
    assert "не запускается" not in result
    assert "пользовател" in result.lower()


@pytest.mark.asyncio
async def test_ensure_postgres_ready_skips_windows_logic_for_remote_host(monkeypatch):
    monkeypatch.setattr(db_bootstrap.asyncpg, "connect", AsyncMock(side_effect=ConnectionRefusedError()))
    monkeypatch.setattr(db_bootstrap.sys, "platform", "win32")
    find_service = MagicMock()
    monkeypatch.setattr(db_bootstrap, "_find_windows_pg_service", find_service)

    result = await db_bootstrap.ensure_postgres_ready(
        "postgresql+asyncpg://user:pw@db.railway.internal:5432/mydb"
    )

    find_service.assert_not_called()
    assert "PostgreSQL недоступен" in result
