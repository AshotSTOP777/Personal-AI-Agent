from __future__ import annotations

import asyncio
import subprocess
import sys
from urllib.parse import urlsplit

import asyncpg

WINGET_INSTALL_HINT = "PostgreSQL не установлен. Установи одной командой: winget install -e --id PostgreSQL.PostgreSQL.16"

CREDENTIAL_ERRORS = (asyncpg.InvalidPasswordError, asyncpg.InvalidAuthorizationSpecificationError)


def _parse(database_url: str) -> dict:
    cleaned = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parts = urlsplit(cleaned)
    return {
        "user": parts.username or "postgres",
        "password": parts.password or "",
        "host": parts.hostname or "localhost",
        "port": parts.port or 5432,
        "dbname": (parts.path or "/").lstrip("/") or "postgres",
    }


def _is_local(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1")


def _run_powershell(script: str, timeout: int) -> str:
    """PowerShell вместо парсинга локализованного вывода sc.exe — Get-CimInstance
    фильтрует по внутреннему Name службы (не зависит от языка Windows). Вывод читается
    как bytes и декодируется с errors='replace', чтобы не падать на кодировке."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        return ""
    raw = result.stdout or b""
    return raw.decode("utf-8", errors="replace").strip()


def _find_windows_pg_service() -> str | None:
    output = _run_powershell(
        "(Get-CimInstance -ClassName Win32_Service -Filter \"Name LIKE 'postgresql%'\" "
        "| Select-Object -First 1 -ExpandProperty Name)",
        timeout=15,
    )
    return output or None


def _is_elevated() -> bool:
    output = _run_powershell(
        "([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()))"
        ".IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)",
        timeout=10,
    )
    return output.lower() == "true"


def _start_windows_service(name: str) -> bool:
    output = _run_powershell(
        f"try {{ Start-Service -Name '{name}' -ErrorAction Stop }} catch {{ }}; "
        f"(Get-Service -Name '{name}').Status",
        timeout=30,
    )
    return output.lower() == "running"


def _classify_credential_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "does not exist" in message:
        return "Роль/пользователь из DATABASE_URL не существует в PostgreSQL — создай её или укажи существующего пользователя в .env."
    return "Неверный пароль PostgreSQL в DATABASE_URL — проверь его в .env (данные не меняю автоматически)."


async def _try_connect(cfg: dict, dbname: str) -> Exception | None:
    try:
        conn = await asyncpg.connect(
            user=cfg["user"], password=cfg["password"], host=cfg["host"], port=cfg["port"],
            database=dbname, timeout=5,
        )
        await conn.close()
        return None
    except Exception as exc:  # noqa: BLE001
        return exc


async def _wait_for_connect(cfg: dict, dbname: str, attempts: int = 6, delay: float = 1.0) -> Exception | None:
    """После старта службы порт может открыться не мгновенно — недолго ждём готовности,
    прежде чем сообщать об ошибке."""
    error: Exception | None = None
    for _ in range(attempts):
        error = await _try_connect(cfg, dbname)
        if error is None:
            return None
        await asyncio.sleep(delay)
    return error


async def _ensure_database_exists(cfg: dict) -> None:
    conn = await asyncpg.connect(
        user=cfg["user"], password=cfg["password"], host=cfg["host"], port=cfg["port"],
        database="postgres", timeout=5,
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", cfg["dbname"])
        if not exists:
            await conn.execute(f'CREATE DATABASE "{cfg["dbname"]}"')
    finally:
        await conn.close()


async def ensure_postgres_ready(database_url: str) -> str:
    """Готовит PostgreSQL к работе: если сервер локально установлен, но остановлен —
    находит (language-independent, через CIM) и запускает Windows-службу, ждёт готовности
    порта; если целевая БД не существует — создаёт её (при наличии прав у настроенного
    пользователя). Различает "не установлен" / "служба остановлена" / "нужны права
    администратора" / "неверный пароль" / "роль не существует". Возвращает 'OK' либо
    короткое сообщение с ОДНИМ конкретным действием. Пароль и другие секреты никогда не
    печатаются. Remote/Railway (не localhost) не трогает Windows-логикой вообще."""
    cfg = _parse(database_url)
    is_windows_local = sys.platform == "win32" and _is_local(cfg["host"])

    error = await _try_connect(cfg, dbname="postgres")

    if error is not None and isinstance(error, CREDENTIAL_ERRORS):
        return _classify_credential_error(error)

    if error is not None and is_windows_local:
        service = _find_windows_pg_service()
        if service is None:
            return WINGET_INSTALL_HINT

        started = _start_windows_service(service)
        if started:
            error = await _wait_for_connect(cfg, dbname="postgres")
            if error is not None and isinstance(error, CREDENTIAL_ERRORS):
                return _classify_credential_error(error)
            if error is not None:
                # Служба подтверждённо Running (started=True), но подключиться всё равно
                # не вышло — это не проблема службы. Чаще всего DATABASE_URL так и остался
                # с плейсхолдером user:password вместо реального пользователя PostgreSQL.
                return (
                    "Служба PostgreSQL запущена, но не удалось подключиться с указанными "
                    "в DATABASE_URL пользователем/паролем (возможно, там ещё плейсхолдер "
                    "user:password) — укажи в .env реального пользователя PostgreSQL "
                    "(обычно postgres) и его пароль."
                )
        elif error is not None:
            if not _is_elevated():
                return f"Служба PostgreSQL '{service}' остановлена и требует прав администратора для запуска. Запусти от администратора: net start \"{service}\""
            return f"Служба PostgreSQL '{service}' не запускается. Попробуй вручную: net start \"{service}\""

    if error is not None:
        return f"PostgreSQL недоступен на {cfg['host']}:{cfg['port']} ({type(error).__name__})"

    try:
        await _ensure_database_exists(cfg)
    except Exception as exc:  # noqa: BLE001
        return f"Не удалось создать/проверить базу '{cfg['dbname']}' — у пользователя из DATABASE_URL нет прав CREATEDB ({type(exc).__name__})."

    return "OK"
