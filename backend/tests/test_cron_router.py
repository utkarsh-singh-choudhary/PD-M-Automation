"""
Tests for app/routers/cron.py's shared-secret auth path. Mocks the job
functions and the DB dependency so this runs without a real Postgres
connection, in line with the rest of this test suite.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
import app.main as main_module


@pytest.fixture
def client():
    main_module.app.dependency_overrides[get_db] = lambda: iter([None])
    yield TestClient(main_module.app)
    main_module.app.dependency_overrides.pop(get_db, None)


def test_rejects_when_cron_secret_unset(client):
    with patch.object(settings, "CRON_SECRET", ""):
        resp = client.post("/api/cron/daily-reminders", headers={"X-Cron-Secret": "anything"})
        assert resp.status_code == 403


def test_rejects_missing_header(client):
    with patch.object(settings, "CRON_SECRET", "supersecret"):
        resp = client.post("/api/cron/daily-reminders")
        assert resp.status_code == 403


def test_rejects_wrong_secret(client):
    with patch.object(settings, "CRON_SECRET", "supersecret"):
        resp = client.post("/api/cron/daily-reminders", headers={"X-Cron-Secret": "wrong"})
        assert resp.status_code == 403


def test_accepts_correct_secret_and_runs_job(client):
    with patch.object(settings, "CRON_SECRET", "supersecret"), \
         patch("app.routers.cron.run_daily_reminder_job") as mock_job:
        resp = client.post("/api/cron/daily-reminders", headers={"X-Cron-Secret": "supersecret"})
        assert resp.status_code == 200
        assert resp.json()["job"] == "daily-reminders"
        mock_job.assert_called_once()


def test_monthly_report_endpoint_runs_job(client):
    with patch.object(settings, "CRON_SECRET", "supersecret"), \
         patch("app.routers.cron.run_monthly_report_job") as mock_job:
        resp = client.post("/api/cron/monthly-report", headers={"X-Cron-Secret": "supersecret"})
        assert resp.status_code == 200
        mock_job.assert_called_once()


def test_sheet_freshness_endpoint_runs_job(client):
    with patch.object(settings, "CRON_SECRET", "supersecret"), \
         patch("app.routers.cron.run_sheet_freshness_check", return_value={"staleness_alert_sent": False, "month_end_alert_sent": False}) as mock_job:
        resp = client.post("/api/cron/sheet-freshness", headers={"X-Cron-Secret": "supersecret"})
        assert resp.status_code == 200
        assert resp.json()["staleness_alert_sent"] is False
        mock_job.assert_called_once()
