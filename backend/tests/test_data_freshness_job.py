"""
Tests for app/jobs/data_freshness_job.py's trigger logic. The job itself
needs a real DB session (ScheduledJob/ImportBatch queries), so these mock
the DB-touching helpers (_latest_completed_import, _claim, _complete) and
the outbound send (send_admin_alert) rather than requiring Postgres - in
line with the rest of this test suite, which runs without a live DB.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.jobs import data_freshness_job as job


def _run(today, latest_uploaded_at, sheet_freshness_days=35, sheet_freshness_month_end_day=25):
    fake_import = MagicMock()
    fake_import.uploaded_at = latest_uploaded_at

    with patch.object(job, "_latest_completed_import", return_value=(fake_import if latest_uploaded_at else None)), \
         patch.object(job, "_claim", return_value=True) as mock_claim, \
         patch.object(job, "_complete") as mock_complete, \
         patch.object(job, "send_admin_alert", return_value={"email_sent": 1}) as mock_alert, \
         patch("app.jobs.data_freshness_job.get_setting") as mock_get_setting:

        mock_get_setting.side_effect = lambda db, key, default=None: {
            "sheet_freshness_days": sheet_freshness_days,
            "sheet_freshness_month_end_day": sheet_freshness_month_end_day,
        }.get(key, default)

        results = job.run_sheet_freshness_check(db=MagicMock(), today=today)
        return results, mock_claim, mock_complete, mock_alert


def test_no_alert_when_recently_imported_and_before_month_end_day():
    today = date(2026, 9, 10)
    latest = datetime(2026, 9, 5)
    results, mock_claim, mock_complete, mock_alert = _run(today, latest)
    assert results == {"staleness_alert_sent": False, "month_end_alert_sent": False}
    mock_alert.assert_not_called()


def test_staleness_alert_fires_past_threshold():
    today = date(2026, 9, 10)
    latest = datetime(2026, 7, 1)  # 71 days ago, threshold is 35
    results, mock_claim, mock_complete, mock_alert = _run(today, latest)
    assert results["staleness_alert_sent"] is True
    assert mock_alert.call_count >= 1


def test_staleness_alert_fires_when_never_imported():
    today = date(2026, 9, 10)
    results, mock_claim, mock_complete, mock_alert = _run(today, None)
    assert results["staleness_alert_sent"] is True


def test_month_end_alert_fires_when_no_import_this_month_past_threshold_day():
    today = date(2026, 9, 26)  # past sheet_freshness_month_end_day=25
    latest = datetime(2026, 8, 1)  # last import was last month, not this one
    results, mock_claim, mock_complete, mock_alert = _run(today, latest)
    assert results["month_end_alert_sent"] is True


def test_month_end_alert_does_not_fire_before_threshold_day():
    today = date(2026, 9, 20)  # before day 25
    latest = datetime(2026, 8, 1)
    results, mock_claim, mock_complete, mock_alert = _run(today, latest)
    assert results["month_end_alert_sent"] is False


def test_month_end_alert_does_not_fire_if_already_imported_this_month():
    today = date(2026, 9, 28)
    latest = datetime(2026, 9, 15)  # already imported this month
    results, mock_claim, mock_complete, mock_alert = _run(today, latest)
    assert results["month_end_alert_sent"] is False


def test_no_send_when_claim_fails_idempotency_guard():
    """If another process already claimed this period's ScheduledJob row,
    this run must not alert again - protects against double-send on a
    scheduler restart or overlapping runs."""
    today = date(2026, 9, 10)
    fake_import = None
    with patch.object(job, "_latest_completed_import", return_value=fake_import), \
         patch.object(job, "_claim", return_value=False), \
         patch.object(job, "send_admin_alert") as mock_alert, \
         patch("app.jobs.data_freshness_job.get_setting") as mock_get_setting:
        mock_get_setting.side_effect = lambda db, key, default=None: default
        results = job.run_sheet_freshness_check(db=MagicMock(), today=today)
        assert results == {"staleness_alert_sent": False, "month_end_alert_sent": False}
        mock_alert.assert_not_called()
