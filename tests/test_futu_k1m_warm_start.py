from datetime import datetime, timedelta, timezone

from src.services.live_feed.futu_k1m_warm_start import (
    build_futu_k1m_warm_start_plan,
    build_futu_k1m_warm_start_selection,
)


RECEIVED = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)


def _session(day: str, symbol: str = "US.AMD"):
    start = datetime.strptime(day + " 09:31:00", "%Y-%m-%d %H:%M:%S")
    rows = []
    for index in range(390):
        stamp = start + timedelta(minutes=index)
        price = 100 + index / 100
        rows.append(
            {
                "code": symbol,
                "time_key": stamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price + 0.1,
                "volume": 1000 + index,
                "turnover": 100000 + index,
            }
        )
    return rows


def test_selects_complete_prior_day_terminal_session_without_next_label():
    prior = _session("2026-10-05")
    latest = _session("2026-10-06")

    plan = build_futu_k1m_warm_start_plan(
        [*prior, *latest],
        received_at=RECEIVED,
        expected_symbol="US.AMD",
    )

    assert plan.status == "PASS"
    assert plan.session_date == "2026-10-06"
    assert len(plan.bars) == 390
    assert plan.bars[-1].bar_end.hour == 20  # 16:00 New York = 20:00 UTC in EDT
    assert plan.closure_anchor_time_key is None
    assert plan.closure_method == "QUALIFIED_PRIOR_SESSION_FULL_GRID"
    assert plan.bars[-1].quality_flags == ("HISTORICAL_QUERY",)
    assert plan.research_cache_seed_eligible is True


def test_selects_latest_session_once_next_provider_label_exists():
    prior = _session("2026-10-05")
    latest = _session("2026-10-06")
    anchor = dict(_session("2026-10-07")[0])

    plan = build_futu_k1m_warm_start_plan(
        [*prior, *latest, anchor],
        received_at=RECEIVED,
        expected_symbol="US.AMD",
    )

    assert plan.status == "PASS"
    assert plan.session_date == "2026-10-06"
    assert len(plan.bars) == 390
    assert plan.closure_anchor_time_key == "2026-10-07 09:31:00"


def test_same_day_latest_session_without_anchor_remains_blocked():
    latest = _session("2026-10-06")

    plan = build_futu_k1m_warm_start_plan(
        latest,
        received_at=datetime(2026, 10, 6, 22, 0, tzinfo=timezone.utc),
        expected_symbol="US.AMD",
    )

    assert plan.status == "BLOCKED"
    assert plan.bars == ()
    assert any("MISSING_LATER_PROVIDER_LABEL" in reason for reason in plan.reasons)


def test_incomplete_session_does_not_become_seed_eligible():
    prior = _session("2026-10-05")[:-1]
    anchor = dict(_session("2026-10-06")[0])

    plan = build_futu_k1m_warm_start_plan(
        [*prior, anchor],
        received_at=RECEIVED,
        expected_symbol="US.AMD",
    )

    assert plan.status == "BLOCKED"
    assert plan.research_cache_seed_eligible is False
    assert plan.bars == ()


def test_symbol_mismatch_fails_closed():
    rows = _session("2026-10-05")
    rows[100] = {**rows[100], "code": "US.NVDA"}

    plan = build_futu_k1m_warm_start_plan(
        rows,
        received_at=RECEIVED,
        expected_symbol="US.AMD",
    )

    assert plan.status == "BLOCKED"
    assert plan.reasons == ("SYMBOL_MISMATCH",)


def test_pass_never_promotes_realtime_or_execution():
    prior = _session("2026-10-05")
    latest = _session("2026-10-06")

    plan = build_futu_k1m_warm_start_plan(
        [*prior, *latest],
        received_at=RECEIVED,
        expected_symbol="US.AMD",
    )
    payload = plan.to_dict()

    assert payload["historical_query"] is True
    assert payload["realtime_currentness_proven"] is False
    assert payload["bar_closure_promotion_authorized"] is False
    assert payload["radar_admission"] == "BLOCKED"
    assert payload["live_trade"] is False
    assert payload["bar_count"] == 390


def test_three_session_selection_is_newest_first_and_seed_eligible():
    rows = [
        *_session("2026-10-02"),
        *_session("2026-10-05"),
        *_session("2026-10-06"),
        dict(_session("2026-10-07")[0]),
    ]

    selection = build_futu_k1m_warm_start_selection(
        rows,
        received_at=RECEIVED,
        expected_symbol="US.AMD",
        requested_sessions=3,
    )

    assert selection.status == "PASS"
    assert selection.research_cache_seed_eligible is True
    assert [plan.session_date for plan in selection.plans] == [
        "2026-10-06",
        "2026-10-05",
        "2026-10-02",
    ]
    assert selection.session_dates == (
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
    )
    assert selection.closure_anchor_time_keys == (
        "2026-10-05 09:31:00",
        "2026-10-06 09:31:00",
        "2026-10-07 09:31:00",
    )
    assert selection.closure_methods == (
        "NEXT_TIME_KEY_PROGRESS",
        "NEXT_TIME_KEY_PROGRESS",
        "NEXT_TIME_KEY_PROGRESS",
    )
    assert selection.bar_count == 1170


def test_three_session_selection_can_use_prior_date_terminal_full_grid():
    rows = [
        *_session("2026-10-02"),
        *_session("2026-10-05"),
        *_session("2026-10-06"),
    ]

    selection = build_futu_k1m_warm_start_selection(
        rows,
        received_at=RECEIVED,
        expected_symbol="US.AMD",
        requested_sessions=3,
    )

    assert selection.status == "PASS"
    assert selection.session_dates == (
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
    )
    assert selection.closure_anchor_time_keys == (
        "2026-10-05 09:31:00",
        "2026-10-06 09:31:00",
    )
    assert selection.closure_methods == (
        "NEXT_TIME_KEY_PROGRESS",
        "NEXT_TIME_KEY_PROGRESS",
        "QUALIFIED_PRIOR_SESSION_FULL_GRID",
    )
    assert selection.bar_count == 1170
    assert selection.plans[0].closure_anchor_time_key is None


def test_two_proven_sessions_do_not_satisfy_three_session_selection():
    rows = [
        *_session("2026-10-05"),
        *_session("2026-10-06"),
        dict(_session("2026-10-07")[0]),
    ]

    selection = build_futu_k1m_warm_start_selection(
        rows,
        received_at=RECEIVED,
        expected_symbol="US.AMD",
        requested_sessions=3,
    )

    assert selection.status == "PARTIAL"
    assert selection.research_cache_seed_eligible is False
    assert len(selection.plans) == 2
    assert selection.bar_count == 780
    assert selection.reasons[0] == "INSUFFICIENT_CLOSURE_PROVEN_SESSIONS:2/3"
