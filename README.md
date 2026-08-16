# Personal AI Agent

Приватный Telegram-бот — личный AI-ассистент. Понимает поручения на русском языке,
сам выбирает нужный инструмент (память, задачи, напоминания, веб-поиск) и выполняет их.

Доступен только владельцу (`TELEGRAM_OWNER_ID`) — все остальные пользователи отклоняются.

## Стек

- Python 3.12+ (разработано и протестировано также на 3.10)
- aiogram 3 (long polling)
- PostgreSQL + SQLAlchemy 2 (async) + Alembic
- Anthropic Python SDK (Claude) через собственный слой `app/ai`
- pydantic-settings, httpx, structlog

## Структура

```
app/
  ai/         — абстракция AIProvider + AnthropicProvider + Coordinator (главный агент)
  bot/        — aiogram handlers, owner-only middleware, форматирование сообщений
  db/         — SQLAlchemy engine/session
  models/     — ORM-модели (Memory, Task, Reminder, ConversationMessage, AiUsageLog)
  services/   — бизнес-логика поверх моделей
  tools/      — инструменты агента (remember, recall_memory, create_task, list_tasks,
                complete_task, create_reminder, web_search) + permissions (SAFE/CONFIRM/CRITICAL)
  workers/    — background worker для напоминаний
  config.py   — pydantic-settings конфигурация
  main.py     — точка входа (long polling + reminder worker)
alembic/      — миграции БД
tests/        — pytest, без реальных обращений к Telegram/Claude API
```

## Установка

```bash
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -e ".[dev]"
```

Заполни `.env` на основе `.env.example` (токен Telegram, ID владельца, Anthropic API key,
строку подключения к PostgreSQL).

## Миграции

```bash
alembic upgrade head
```

## Запуск

```bash
python -m app.main
```

## Тесты

```bash
pytest
```

Тесты используют SQLite in-memory и моки вместо реальных Telegram/Claude API.

## Что уже работает

- Owner-only доступ (middleware блокирует всех, кроме `TELEGRAM_OWNER_ID`).
- Coordinator: обрабатывает сообщение, вызывает инструменты через Claude tool use,
  ограничивает число шагов (MAX_TOOL_ITERATIONS), логирует usage токенов, проверяет
  дневной лимит токенов.
- 7 инструментов со строгими Pydantic-схемами.
- Память фактов (`memories`), задачи (`tasks`), напоминания (`reminders`, БД-бэкед,
  переживают перезапуск) с background worker'ом.
- История диалога хранится в БД, но в модель уходит только ограниченное окно последних
  сообщений — не вся история.
- Механизм permissions (SAFE/CONFIRM/CRITICAL) готов; все текущие инструменты — SAFE.
  Как только появятся более рискованные инструменты (отправка сообщений, публикация,
  платежи), Coordinator уже умеет останавливаться и запрашивать подтверждение вместо
  автоматического выполнения.
- 19 тестов (owner access, tasks, reminders, memory, permissions, tool calls через
  Coordinator с фейковым AI-провайдером).

## Что ещё нужно настроить перед первым реальным запуском

- Реальный PostgreSQL и `DATABASE_URL` (для тестов используется SQLite, для прод — Postgres).
- Реальные `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_ID`, `ANTHROPIC_API_KEY` в `.env`.
- `alembic upgrade head` перед первым запуском.
- `web_search` использует HTML-скрапинг DuckDuckGo без API-ключа — рабочий вариант для
  старта, но при желании стоит заменить на официальный поисковый API.
- Деплой на Railway (сознательно не выполнялся в рамках этой задачи).
- UI для подтверждения CONFIRM/CRITICAL действий в Telegram (сейчас Coordinator
  формирует текст с запросом подтверждения, но интерактивной кнопки/сценария
  подтверждения через `/confirm` пока нет — добавится вместе с первым таким инструментом).
