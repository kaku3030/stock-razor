"""Fail-closed OpenD 16:00 ET terminal minute reconciliation regressions."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.services.live_feed.futu_k1m_history import normalize_futu_k1m_history_rows
from src.services.live_feed.us_postclose_terminal_reconciliation import (
    reconcile_us_postclose_terminal_minutes,
    postclose_history_retry_due,
)

NY = ZoneInfo("America/New_York")
DAY = "2026-10-14"
AT = datetime(2026, 10, 14, 16, 31, tzinfo=NY)


def _rows(day=DAY):
    start = datetime.strptime(day + " 09:31:00", "%Y-%m-%d %H:%M:%S")
    return [
        {
            "code": "US.NVDA",
            "time_key": (start + timedelta(minutes=minute)).strftime("%Y-%m-%d %H:%M:%S"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000.0, "turnover": 100_500.0,
        }
        for minute in range(390)
    ]


class _Cache:
    def __init__(self, preterminal=True):
        bars = normalize_futu_k1m_history_rows(
            _rows(), received_at=AT,
            expected_symbol="US.NVDA",
            allow_completed_prior_session_tail=True,
        ).bars
        self.values = [replace(bars[-2], quality_flags=())] if preterminal else []
        self.ingestions = 0

    def minute_bars(self, symbol):
        assert symbol == "US.NVDA"
        return tuple(self.values)

    def ingest(self, bar):
        self.values.append(bar)
        self.ingestions += 1
        return True


def _call(*, at=AT, rows=None, state="AFTER_HOURS_BEGIN", label=DAY + " 16:00:00", cache=None, next_page=None):
    calls = []
    cache = cache if cache is not None else _Cache()

    def fetch(symbol, start, end, page):
        calls.append((symbol, start, end, page))
        return _rows() if rows is None else rows, next_page

    report = reconcile_us_postclose_terminal_minutes(
        ["US.NVDA"],
        fetch_page=fetch,
        market_data=cache,
        latest_time_keys={"US.NVDA": label},
        observed_at=at,
        market_state=state,
    )
    return report, calls, cache


def test_1630_afterhours_full_grid_ends_with_historical_only_closure():
    report, calls, cache = _call()
    assert report["status"] == "PASS_HISTORICAL_ONLY"
    assert report["provider_requests"] == 1
    assert calls == [("US.NVDA", DAY, DAY, None)]
    assert report["seeded_count"] == 1 == cache.ingestions
    final = cache.values[-1]
    assert final.bar_start == datetime(2026, 10, 14, 15, 59, tzinfo=NY)
    assert final.bar_end == datetime(2026, 10, 14, 16, 0, tzinfo=NY)
    assert "HISTORICAL_QUERY" in final.quality_flags
    assert final.health.signal_permission.value != "normal"
    assert report["provider_finality"] == "NOT_VERIFIED"
    assert report["bar_closure_promotion_authorized"] is False
    assert report["currentness_proven"] is False
    assert report["radar_admission"] == "BLOCKED"
    assert report["source_arbiter_admission"] == "BLOCKED"
    assert report["paper_auto_ready"] is False
    assert report["live_trade"] is False


@pytest.mark.parametrize("when,market", [
    (datetime(2026, 10, 14, 16, 29, tzinfo=NY), "AFTER_HOURS_BEGIN"),
    (AT, "MORNING"),
    (AT, "UNKNOWN"),
    (AT, "PRE_MARKET_BEGIN"),
])
def test_no_query_outside_qualified_postclose_window(when, market):
    report, calls, cache = _call(at=when, state=market)
    assert report["status"] == "NOT_DUE"
    assert not calls and cache.ingestions == 0


@pytest.mark.parametrize("last_key", [
    "2026-10-13 16:00:00",
    "2026-10-14 15:58:00",
    "bad-label",
])
def test_absent_regular_final_label_never_triggers_provider(last_key):
    report, calls, cache = _call(label=last_key)
    assert report["status"] == "BLOCKED"
    assert not calls and cache.ingestions == 0


def test_overnight_same_ny_day_after_close_can_reconcile_historically():
    report, calls, cache = _call(
        at=datetime(2026, 10, 14, 21, 1, tzinfo=NY),
        state="OVERNIGHT",
    )
    assert report["status"] == "PASS_HISTORICAL_ONLY"
    assert len(calls) == 1 and cache.ingestions == 1
    assert report["bar_closure_promotion_authorized"] is False


def test_actual_incident_no_1600_push_with_last_1559_label_is_repaired():
    report, calls, cache = _call(label=DAY + " 15:59:00")
    assert len(calls) == 1
    assert report["status"] == "PASS_HISTORICAL_ONLY"
    assert report["provider_requests"] == 1
    assert cache.ingestions == 1
    assert "HISTORICAL_QUERY" in cache.values[-1].quality_flags
    assert report["bar_closure_promotion_authorized"] is False


def test_missing_regular_1558_live_evidence_does_not_trigger_query():
    cache = _Cache(preterminal=False)
    report, calls, _ = _call(cache=cache)
    assert report["status"] == "BLOCKED"
    assert not calls and cache.ingestions == 0
    assert report["symbols"]["US.NVDA"]["reason"] == "MISSING_PRETERMINAL_LIVE_EVIDENCE"


@pytest.mark.parametrize("mutation", [
    lambda rows: rows.pop(),
    lambda rows: rows.pop(80),
    lambda rows: rows[80].update({"time_key": rows[79]["time_key"]}),
])
def test_incomplete_duplicate_or_389_row_provider_grid_does_not_seed(mutation):
    rows = _rows()
    mutation(rows)
    report, calls, cache = _call(rows=rows)
    assert len(calls) == 1
    assert report["status"] == "BLOCKED"
    assert cache.ingestions == 0


def test_pagination_required_never_qualifies_partial_page():
    report, calls, cache = _call(next_page="more")
    assert report["symbols"]["US.NVDA"]["reason"] == "HISTORY_PAGINATION_NOT_EXHAUSTED"
    assert len(calls) == 1 and cache.ingestions == 0


def test_existing_terminal_live_bar_is_not_overwritten_by_historical():
    cache = _Cache()
    original = normalize_futu_k1m_history_rows(
        _rows(), received_at=AT,
        expected_symbol="US.NVDA",
        allow_completed_prior_session_tail=True,
    ).bars[-1]
    cache.values.append(original)
    report, calls, _ = _call(cache=cache)
    assert report["status"] == "ALREADY_PRESENT"
    assert report["symbols"]["US.NVDA"]["status"] == "ALREADY_PRESENT"
    assert cache.ingestions == 0
    assert not calls


def test_winter_timezone_boundary_is_exchange_local_not_fixed_utc():
    # 16:30 NY winter is 21:30 UTC, not 20:30 UTC.
    at = datetime(2026, 12, 14, 21, 29, tzinfo=timezone.utc)
    report, calls, cache = _call(at=at, label="2026-12-14 16:00:00")
    assert report["status"] == "NOT_DUE"
    assert not calls and cache.ingestions == 0


def test_bad_clock_and_symbol_cannot_query():
    report, calls, cache = _call(at=datetime(2026, 10, 14, 16, 31))
    assert report["status"] == "BLOCKED"
    assert not calls and cache.ingestions == 0


def test_installer_wires_one_shot_historical_reconciliation_without_promotion():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "ops/aws/install_us_opend_livefeed.sh").read_text()
    assert "reconcile_us_postclose_terminal_minutes" in script
    assert "postclose_attempt_count" in script
    assert "postclose_last_attempt_at" in script
    assert "postclose_history_retry_due(" in script
    assert '"postclose_reconciliation":postclose_reconciliation' in script
    assert "or postclose_seeded_this_pass > 0" in script


def test_existing_incomplete_terminal_is_not_accepted_or_replaced():
    cache = _Cache()
    final = normalize_futu_k1m_history_rows(
        _rows(), received_at=AT,
        expected_symbol="US.NVDA",
        allow_completed_prior_session_tail=True,
    ).bars[-1]
    cache.values.append(replace(final, is_complete=False))
    report, calls, _ = _call(cache=cache)
    assert report["status"] == "BLOCKED"
    assert report["symbols"]["US.NVDA"]["reason"] == "EXISTING_TERMINAL_BAR_UNQUALIFIED"
    assert report["seeded_count"] == 0
    assert cache.ingestions == 0
    assert calls == []


def test_postclose_history_retry_is_at_most_twice_after_30m_with_real_failure():
    call = lambda **kwargs: postclose_history_retry_due(observed_at=AT, **kwargs)
    assert call(attempts=0, last_attempt_at=None, prior_status="NOT_DUE")
    # Original one-shot failed provider call must not retry in a hot 5s loop.
    failed_at = AT - timedelta(minutes=29)
    assert not call(attempts=1, last_attempt_at=failed_at, prior_status="BLOCKED")
    exactly_30m = AT - timedelta(minutes=30)
    assert call(attempts=1, last_attempt_at=exactly_30m, prior_status="BLOCKED")
    assert call(attempts=1, last_attempt_at=exactly_30m, prior_status="PARTIAL_HISTORICAL_ONLY")
    # Full success or already present must never query a second time.
    assert not call(attempts=1, last_attempt_at=exactly_30m, prior_status="PASS_HISTORICAL_ONLY")
    assert not call(attempts=1, last_attempt_at=exactly_30m, prior_status="ALREADY_PRESENT")
    assert not call(attempts=2, last_attempt_at=exactly_30m, prior_status="BLOCKED")


def test_postclose_retry_rejects_missing_clock_or_old_session_state():
    call = lambda **kwargs: postclose_history_retry_due(observed_at=AT, **kwargs)
    assert not call(attempts=0, last_attempt_at=AT, prior_status="NOT_DUE")
    assert not call(attempts=-1, last_attempt_at=None, prior_status="NOT_DUE")
    assert not call(attempts=True, last_attempt_at=None, prior_status="NOT_DUE")
    assert not call(attempts=1, last_attempt_at=None, prior_status="BLOCKED")
    assert not call(attempts=1, last_attempt_at=AT + timedelta(seconds=1), prior_status="BLOCKED")
    assert not call(attempts=1, last_attempt_at=AT - timedelta(days=2), prior_status="BLOCKED")
    assert not call(attempts=1, last_attempt_at=AT.replace(tzinfo=None), prior_status="BLOCKED")
    assert not postclose_history_retry_due(
        attempts=1, last_attempt_at=AT - timedelta(minutes=30),
        observed_at=AT.replace(tzinfo=None), prior_status="BLOCKED",
    )