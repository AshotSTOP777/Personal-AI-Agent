from __future__ import annotations

import re
import subprocess
import sys
from urllib.parse import urlsplit

import asyncpg

WINGET_INSTALL_HINT = "PostgreSQL не установлен. Установи одной командой: winget install -e --id PostgreSQL.PostgreSQL.16"


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


def _run_decoded(args: list[str], timeout: int) -> str:
    """Запускает subprocess и декодирует stdout как bytes с errors='replace' —
    sc.exe/service-имена могут быть в системной кодовой странице, отличной от UTF-8,
    поэтому text=True (charmap) иногда падает с UnicodeDecodeError."""
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout)
    except Exception:  # noqa: BLE001
        return ""
    raw = result.stdout or b""
    return raw.decode("utf-8", errors="replace")


def _find_windows_pg_service() -> str | None:
    output = _run_decoded(["sc", "query", "state=", "all"], timeout=15)
    for name in re.findall(r"SERVICE_NAME:\s*(\S+)", output):
        if "postgres" in name.lower():
            return name
    return None


def _start_windows_service(name: str) -> bool:
    try:
        result = subprocess.run(["net", "start", name], capture_output=True, timeout=30)
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


CREDENTIAL_ERRORS = (asyncpg.InvalidPasswordError, asyncpg.InvalidAuthorizationSpecificationError)


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
    находит и запускает Windows-службу; если целевая БД не существует — создаёт её.
    Различает "не установлен" / "служба остановлена" / "неверные credentials".
    Возвращает 'OK' либо короткое сообщение с ОДНИМ конкретным действием. Пароль
    и другие секреты никогда не печатаются."""
    cfg = _parse(database_url)
    is_windows_local = sys.platform == "win32" and _is_local(cfg["host"])

    error = await _try_connect(cfg, dbname="postgres")

    if error is not None and isinstance(error, CREDENTIAL_ERRORS):
        return "Неверные пользователь/пароль PostgreSQL — проверь DATABASE_URL в .env (данные не меняю автоматически)."

    if error is not None and is_windows_local:
        service = _find_windows_pg_service()
        if service is None:
            return WINGET_INSTALL_HINT
        if _start_windows_service(service):
            error = await _try_connect(cfg, dbname="postgres")
            if error is not None and isinstance(error, CREDENTIAL_ERRORS):
                return "Неверные пользователь/пароль PostgreSQL — проверь DATABASE_URL в .env (данные не меняю автоматически)."
        if error is not None:
            return f"Служба PostgreSQL '{service}' не запускается. Запусти вручную: net start \"{service}\""

    if error is not None:
        return f"PostgreSQL недоступен на {cfg['host']}:{cfg['port']} ({type(error).__name__})"

    try:
        await _ensure_database_exists(cfg)
    except Exception as exc:  # noqa: BLE001
        return f"Не удалось создать/проверить базу '{cfg['dbname']}' ({type(exc).__name__})"

    return "OK"
