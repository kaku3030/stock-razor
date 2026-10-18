"""Same-day US OpenD K1M 16:00 tail: full-grid + postclose buffer only.

No provider requests, network, order submissions, or AWS access in these tests.
Full 390-row provider historical data is mandatory and remains research-only.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.services.live_feed.futu_k1m_history import normalize_futu_k1m_history_rows
from src.services.live_feed.futu_k1m_warm_start import (
    build_futu_k1m_warm_start_plan,
)


def _session(day: str):
    start = datetime.strptime(day + " 09:31:00", "%Y-%m-%d %H:%M:%S")
    return [
        {
            "code": "US.AMD",
            "time_key": (start + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
            "open": 100.0 + i / 100,
            "high": 100.5 + i / 100,
            "low": 99.9 + i / 100,
            "close": 100.2 + i / 100,
            "volume": 1000 + i,
            # Model valid minute VWAP near close for every synthetic row.
            "turnover": (100.2 + i / 100) * (1000 + i),
        }
        for i in range(390)
    ]


@pytest.mark.parametrize(
    ("day", "before", "allowed"),
    [
        ("2026-10-06", datetime(2026, 10, 6, 20, 29, 59, tzinfo=timezone.utc),
         datetime(2026, 10, 6, 20, 30, tzinfo=timezone.utc)),
        # New York winter close is 21:00Z, not 20:00Z.
        ("2026-01-06", datetime(2026, 1, 6, 21, 29, 59, tzinfo=timezone.utc),
         datetime(2026, 1, 6, 21, 30, tzinfo=timezone.utc)),
    ],
)
def test_same_day_completed_provider_grid_only_after_ny_1630_buffer(day, before, allowed):
    rows = _session(day)
    premature = normalize_futu_k1m_history_rows(
        rows, received_at=before, expected_symbol="US.AMD",
        allow_completed_prior_session_tail=True,
    )
    assert len(premature.bars) == 389
    assert premature.unresolved_tail.time_key == day + " 16:00:00"
    assert premature.closure_method == "NEXT_TIME_KEY_PROGRESS"
    assert premature.radar_admission == "BLOCKED"

    complete = normalize_futu_k1m_history_rows(
        rows, received_at=allowed, expected_symbol="US.AMD",
        allow_completed_prior_session_tail=True,
    )
    assert len(complete.bars) == 390
    assert complete.bars[-1].is_closed is True
    assert complete.bars[-1].is_complete is True
    assert complete.bars[-1].quality_flags == ("HISTORICAL_QUERY",)
    assert complete.unresolved_tail is None
    assert complete.closure_method == "QUALIFIED_POST_SESSION_FULL_GRID"
    assert complete.research_only is True
    assert complete.can_promote is False
    assert complete.radar_admission == "BLOCKED"
    assert complete.live_trade is False


def test_postclose_full_grid_without_explicit_optin_remains_unresolved():
    r = normalize_futu_k1m_history_rows(
        _session("2026-10-12"),
        received_at=datetime(2026, 10, 12, 23, 55, tzinfo=timezone.utc),
        expected_symbol="US.AMD",
    )
    assert len(r.bars) == 389
    assert r.unresolved_tail.time_key == "2026-10-12 16:00:00"
    assert r.closure_method == "NEXT_TIME_KEY_PROGRESS"


@pytest.mark.parametrize("mutation", ["remove_last", "remove_interior", "duplicate"])
def test_same_day_missing_or_malformed_provider_grid_cannot_seed(mutation):
    rows = _session("2026-10-12")
    if mutation == "remove_last":
        rows.pop()
    elif mutation == "remove_interior":
        rows.pop(90)
    else:
        rows[90]["time_key"] = rows[89]["time_key"]
    r = build_futu_k1m_warm_start_plan(
        rows, received_at=datetime(2026, 10, 12, 23, 55, tzinfo=timezone.utc),
        expected_symbol="US.AMD",
    )
    assert r.status == "BLOCKED"
    assert r.research_cache_seed_eligible is False
    assert r.bars == ()
    assert r.radar_admission == "BLOCKED"
    assert r.live_trade is False


def test_same_day_after_close_full_390_provider_rows_seeds_research_only():
    plan = build_futu_k1m_warm_start_plan(
        _session("2026-10-12"),
        received_at=datetime(2026, 10, 12, 23, 55, tzinfo=timezone.utc),
        expected_symbol="US.AMD",
    )
    assert plan.status == "PASS"
    assert len(plan.bars) == 390
    assert plan.bars[-1].bar_start == datetime(
        2026, 10, 12, 19, 59, tzinfo=timezone.utc
    )
    assert plan.bars[-1].bar_end == datetime(
        2026, 10, 12, 20, 0, tzinfo=timezone.utc
    )
    assert plan.bars[-1].quality_flags == ("HISTORICAL_QUERY",)
    assert plan.closure_method == "QUALIFIED_POST_SESSION_FULL_GRID"
    assert plan.closure_anchor_time_key is None
    assert plan.realtime_currentness_proven is False
    assert plan.bar_closure_promotion_authorized is False
    assert plan.research_cache_seed_eligible is True
    assert plan.radar_admission == "BLOCKED"
    assert plan.live_trade is False
