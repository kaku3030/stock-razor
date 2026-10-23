"""Frame-count diagnostics must match the real TickFlow cache contract."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data_provider.cn_tickflow_research_cache import _ALLOWED_PERIODS
from scripts.audit_cn_tickflow_research_runtime import summarize_private_frame_progress

NOW = datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc)


def frame(count):
    return {
        "rows": [
            {"label": (NOW - timedelta(days=count-i)).strftime("%Y-%m-%d 00:00"),
             "amount_availability": "SDK_OMITTED", "close": 987654.321}
            for i in range(count)
        ],
        "quarantined_unverified_rows_count": 0,
        "quarantine_reason_counts": {},
    }


@pytest.mark.parametrize(("period", "bucket"), [
    ("1m", "145_TO_240"), ("5m", "97_TO_144"),
    ("15m", "25_TO_96"), ("60m", "FOUR_TO_24"), ("1d", "25_TO_96"),
])
def test_writer_maximum_remains_visible_without_prices_or_admission(period, bucket):
    result = summarize_private_frame_progress(
        frame(_ALLOWED_PERIODS[period]), timeframe=period, now_utc=NOW,
    )
    assert result["retained_bar_count_bucket"] == bucket
    assert result["quarantined_rows_bucket"] == "ZERO"
    assert result["last_due_grid"] == "NO_SESSION_GRID_DUE"
    assert "987654" not in str(result) and "2026" not in str(result)
    assert "radar_admission" not in result and "live_trade" not in result


@pytest.mark.parametrize("period", tuple(_ALLOWED_PERIODS))
def test_above_writer_bound_is_still_unknown(period):
    result = summarize_private_frame_progress(
        frame(_ALLOWED_PERIODS[period]+1), timeframe=period, now_utc=NOW,
    )
    assert result["retained_bar_count_bucket"] == "UNKNOWN"


def test_public_workflow_accepts_the_full_minute_count_bucket():
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/audit-cn-tickflow-live-research.yml"
    assert '"145_TO_240"' in workflow.read_text(encoding="utf-8")


def minute_frame(clocks):
    return {
        "rows": [{"label": "2026-10-23 " + clock,
                  "amount_availability": "SDK_OMITTED"} for clock in clocks],
        "quarantined_unverified_rows_count": 0,
        "quarantine_reason_counts": {},
    }


def test_recent_legal_minute_inside_grace_does_not_invalidate_due_grid():
    # 09:34 is received legally; only through 09:33 is due at 09:34:45.
    result = summarize_private_frame_progress(
        minute_frame(["09:31", "09:32", "09:33", "09:34"]),
        timeframe="1m", now_utc=datetime(2026, 10, 23, 1, 34, 45, tzinfo=timezone.utc),
    )
    assert result["due_grid_continuity"] == "ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY"


def test_recent_minute_does_not_conceal_an_earlier_due_gap():
    result = summarize_private_frame_progress(
        minute_frame(["09:31", "09:33", "09:34", "09:35"]),
        timeframe="1m", now_utc=datetime(2026, 10, 23, 1, 35, 45, tzinfo=timezone.utc),
    )
    assert result["due_grid_continuity"] == "ONE_DUE_LABEL_MISSING"


@pytest.mark.parametrize("clocks", [
    ["09:31", "09:32", "09:33", "09:35"],  # future
    ["09:31", "09:32", "09:34", "09:34"],  # duplicate inside grace
    ["09:30", "09:32", "09:33", "09:34"],  # off grid
])
def test_grace_audit_keeps_future_duplicate_and_off_grid_invalid(clocks):
    result = summarize_private_frame_progress(
        minute_frame(clocks), timeframe="1m",
        now_utc=datetime(2026, 10, 23, 1, 34, 45, tzinfo=timezone.utc),
    )
    assert result["due_grid_continuity"] == "INVALID_TODAY_LABEL_GRID"
