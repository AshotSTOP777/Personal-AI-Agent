from __future__ import annotations

from app.bootstrap import check_email, check_tools, check_workers


def test_check_tools_reports_registered_count():
    assert check_tools().startswith("OK")


def test_check_workers_imports_successfully():
    assert check_workers() == "OK"


def test_check_email_reports_skip_when_not_configured(monkeypatch):
    monkeypatch.setattr("app.bootstrap.settings.gmail_client_id", "")
    monkeypatch.setattr("app.bootstrap.settings.email_address", "")
    assert check_email().startswith("SKIP")
