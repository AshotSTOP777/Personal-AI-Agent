from __future__ import annotations

import datetime as dt
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.ai.base import AIResponse, TokenUsage, ToolCall
from app.ai.coordinator import Coordinator
from app.ai.system_prompt import build_system_prompt
from app.services import job_service
from app.tools.email_send import EmailSendTool
from app.tools.permissions import PermissionLevel
from app.tools.registry import default_registry
from app.workers.job_worker import JobWorker, confirm_job


class ScriptedProvider:
    def __init__(self, responses: list[AIResponse]) -> None:
        self._responses = responses
        self.calls = 0

    async def generate(self, system, messages, tools, max_tokens=1024) -> AIResponse:
        self.calls += 1
        return self._responses.pop(0)


def _usage() -> TokenUsage:
    return TokenUsage(input_tokens=10, output_tokens=5)


def _final_response(text: str) -> AIResponse:
    return AIResponse(
        text=text, tool_calls=[], raw_content=[{"type": "text", "text": text}], stop_reason="end_turn", usage=_usage()
    )


def _tool_call_response(call_id: str, name: str, args: dict[str, Any]) -> AIResponse:
    return AIResponse(
        text="",
        tool_calls=[ToolCall(id=call_id, name=name, input=args)],
        raw_content=[{"type": "tool_use", "id": call_id, "name": name, "input": args}],
        stop_reason="tool_use",
        usage=_usage(),
    )


def _make_coordinator(provider: ScriptedProvider) -> Coordinator:
    return Coordinator(provider=provider, tool_registry=default_registry, history_window=10, daily_token_limit=200_000)


def _make_worker(coordinator: Coordinator) -> tuple[JobWorker, AsyncMock]:
    bot = AsyncMock()
    worker = JobWorker(bot=bot, coordinator=coordinator, owner_id=1, poll_interval_seconds=3600, max_runs=100)
    return worker, bot


@pytest.mark.asyncio
async def test_job_is_saved_and_can_be_reloaded(db_session):
    job = await job_service.create_job(db_session, user_id=1, goal="Проверяй раз в час курс доллара")
    fetched = await job_service.get_job(db_session, job.id)

    assert fetched is not None
    assert fetched.goal == "Проверяй раз в час курс доллара"
    assert fetched.status.value == "active"
    assert fetched.run_count == 0
    assert fetched.context == {}


@pytest.mark.asyncio
async def test_waiting_job_with_no_update_stays_waiting_and_is_silent(db_session):
    job = await job_service.create_job(db_session, user_id=1, goal="Проверяй новые варианты")
    provider = ScriptedProvider([_final_response("Ничего нового.")])
    coordinator = _make_coordinator(provider)
    worker, bot = _make_worker(coordinator)

    await worker.run_job(db_session, job)

    updated = await job_service.get_job(db_session, job.id)
    assert updated.status.value == "waiting"
    assert updated.run_count == 1
    assert updated.next_run_at is not None
    assert updated.context["messages"]  # контекст сохранён для продолжения
    bot.send_message.assert_not_awaited()  # нет изменений — не спамим


@pytest.mark.asyncio
async def test_waiting_job_continues_with_saved_context_on_next_run(db_session):
    job = await job_service.create_job(db_session, user_id=1, goal="Проверяй новые варианты")
    provider = ScriptedProvider([_final_response("Ничего нового.")])
    worker, _ = _make_worker(_make_coordinator(provider))
    await worker.run_job(db_session, job)
    job = await job_service.get_job(db_session, job.id)
    saved_messages = job.context["messages"]
    assert len(saved_messages) >= 2  # исходная цель + предыдущий ответ модели

    provider2 = ScriptedProvider([_final_response("[OUTCOME:DONE] Нашёл подходящий вариант: example.com/deal")])
    worker2, bot2 = _make_worker(_make_coordinator(provider2))
    await worker2.run_job(db_session, job)

    finished = await job_service.get_job(db_session, job.id)
    assert finished.status.value == "done"
    bot2.send_message.assert_awaited_once()
    sent_text = bot2.send_message.call_args.args[1]
    assert "example.com/deal" in sent_text
    assert "OUTCOME" not in sent_text  # тег статуса не должен уходить владельцу


@pytest.mark.asyncio
async def test_confirm_pauses_job_then_resumes_after_approval(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    sent = []
    monkeypatch.setattr(
        "app.tools.email_send.build_email_provider",
        lambda settings: type("Fake", (), {"send": staticmethod(lambda to, s, b: sent.append((to, s, b)))})(),
    )

    job = await job_service.create_job(db_session, user_id=1, goal="Дождись ответа от друга по почте")
    provider = ScriptedProvider(
        [_tool_call_response("call_1", "email_send", {"to": "friend@example.com", "subject": "Hi", "body": "Text"})]
    )
    coordinator = _make_coordinator(provider)
    worker, bot = _make_worker(coordinator)

    await worker.run_job(db_session, job)

    paused = await job_service.get_job(db_session, job.id)
    assert paused.status.value == "paused"
    assert len(sent) == 0
    bot.send_message.assert_awaited_once()  # уведомили о необходимости подтверждения

    assert provider.calls == 1

    # добавляем в тот же ScriptedProvider ответ для продолжения после подтверждения
    provider._responses.append(_final_response("[OUTCOME:DONE] Письмо отправлено другу."))
    result_text = await confirm_job(db_session, coordinator, paused)

    assert len(sent) == 1  # выполнено ровно один раз
    resumed = await job_service.get_job(db_session, job.id)
    assert resumed.status.value == "done"
    assert "отправлено" in result_text


@pytest.mark.asyncio
async def test_repeated_confirm_job_does_not_resend(db_session, monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    sent = []
    monkeypatch.setattr(
        "app.tools.email_send.build_email_provider",
        lambda settings: type("Fake", (), {"send": staticmethod(lambda to, s, b: sent.append((to, s, b)))})(),
    )

    job = await job_service.create_job(db_session, user_id=1, goal="Дождись ответа от друга по почте")
    provider = ScriptedProvider(
        [
            _tool_call_response("call_1", "email_send", {"to": "friend@example.com", "subject": "Hi", "body": "Text"}),
            _final_response("[OUTCOME:DONE] Письмо отправлено другу."),
        ]
    )
    coordinator = _make_coordinator(provider)
    worker, _ = _make_worker(coordinator)

    await worker.run_job(db_session, job)
    paused = await job_service.get_job(db_session, job.id)
    await confirm_job(db_session, coordinator, paused)
    assert len(sent) == 1

    done_job = await job_service.get_job(db_session, job.id)
    second_text = await confirm_job(db_session, coordinator, done_job)

    assert len(sent) == 1  # письмо не ушло повторно
    assert "не найдено состояние" in second_text.lower()


def test_email_to_own_address_does_not_require_confirm(monkeypatch):
    monkeypatch.setattr("app.tools.email_send.settings.email_address", "owner@example.com")
    tool = EmailSendTool()

    assert tool.permission_for({"to": "owner@example.com"}) == PermissionLevel.SAFE
    assert tool.permission_for({"to": "other@example.com"}) == PermissionLevel.CONFIRM


def test_build_system_prompt_contains_current_date():
    today = dt.date.today().isoformat()
    prompt = build_system_prompt()
    assert today in prompt
