from datetime import datetime, timezone

import pytest

from src.services.live_feed.futu_k1m_currentness import (
    classify_futu_us_k1m_currentness,
    futu_us_market_state_to_session,
    summarize_futu_k1m_currentness,
)


def test_premarket_cached_prior_close_is_not_realtime_evidence():
    result = classify_futu_us_k1m_currentness(
        "2026-10-05 16:00:00",
        observed_at_utc=datetime(2026, 10, 6, 8, 50, 44, tzinfo=timezone.utc),
        market_state="PRE_MARKET_BEGIN",
    )

    assert result.status == "NOT_APPLICABLE"
    assert result.reason == "EXTENDED_SESSION_K1M_CURRENTNESS_UNQUALIFIED"
    assert result.delivery_mode == "UNKNOWN"
    assert result.radar_admission == "BLOCKED"
    assert result.live_trade is False
    assert result.can_promote is False


def test_regular_session_fresh_forming_minute_can_pass_currentness_only():
    result = classify_futu_us_k1m_currentness(
        "2026-10-06 09:35:00",
        observed_at_utc=datetime(2026, 10, 6, 13, 35, 47, tzinfo=timezone.utc),
        market_state="MORNING",
    )

    assert result.status == "PASS"
    assert result.age_seconds == 47
    assert result.delivery_mode == "UNKNOWN"
    assert result.radar_admission == "BLOCKED"
    assert result.can_promote is False


def test_regular_session_stale_k1m_fails_closed():
    result = classify_futu_us_k1m_currentness(
        "2026-10-06 09:30:00",
        observed_at_utc=datetime(2026, 10, 6, 13, 35, tzinfo=timezone.utc),
        market_state="MORNING",
    )

    assert result.status == "FAIL"
    assert result.reason == "K1M_STALE_DURING_REGULAR_SESSION"
    assert result.age_seconds == 300


def test_end_labeled_forming_minute_covers_observation_and_passes():
    result = classify_futu_us_k1m_currentness(
        "2026-10-06 09:49:00",
        observed_at_utc=datetime(2026, 10, 6, 13, 48, 33, tzinfo=timezone.utc),
        market_state="AFTERNOON",
    )

    assert result.status == "PASS"
    assert result.reason == "K1M_FORMING_INTERVAL_COVERS_OBSERVATION"
    assert result.age_seconds == 0
    assert result.end_offset_seconds == -27
    assert result.interval_start_utc == datetime(
        2026, 10, 6, 13, 48, tzinfo=timezone.utc
    )
    assert result.interval_end_utc == datetime(
        2026, 10, 6, 13, 49, tzinfo=timezone.utc
    )


def test_interval_whose_start_is_still_in_future_fails_closed():
    result = classify_futu_us_k1m_currentness(
        "2026-10-06 09:37:00",
        observed_at_utc=datetime(2026, 10, 6, 13, 35, tzinfo=timezone.utc),
        market_state="MORNING",
    )

    assert result.status == "FAIL"
    assert result.reason == "K1M_INTERVAL_NOT_STARTED"
    assert result.end_offset_seconds == -120


@pytest.mark.parametrize("state", ["CLOSED", "WAITING_OPEN", "NONE"])
def test_closed_market_states_are_not_applicable(state):
    result = classify_futu_us_k1m_currentness(
        "2026-10-05 16:00:00",
        observed_at_utc=datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc),
        market_state=state,
    )
    assert result.status == "NOT_APPLICABLE"
    assert result.reason == "MARKET_NOT_REGULAR_SESSION"


def test_unknown_market_state_never_promotes_currentness():
    result = classify_futu_us_k1m_currentness(
        "2026-10-06 09:35:00",
        observed_at_utc=datetime(2026, 10, 6, 13, 35, 10, tzinfo=timezone.utc),
        market_state="SOMETHING_NEW",
    )
    assert result.status == "UNKNOWN"
    assert result.radar_admission == "BLOCKED"


def test_invalid_time_key_during_regular_session_is_fail_closed():
    result = classify_futu_us_k1m_currentness(
        "not-a-time",
        observed_at_utc=datetime(2026, 10, 6, 13, 35, tzinfo=timezone.utc),
        market_state="MORNING",
    )
    assert result.status == "FAIL"
    assert result.reason == "INVALID_K1M_TIME_KEY"


def test_summary_requires_all_regular_streams_to_pass():
    observed = datetime(2026, 10, 6, 13, 35, 30, tzinfo=timezone.utc)
    passed = classify_futu_us_k1m_currentness(
        "2026-10-06 09:35:00", observed_at_utc=observed, market_state="MORNING"
    )
    stale = classify_futu_us_k1m_currentness(
        "2026-10-06 09:30:00", observed_at_utc=observed, market_state="MORNING"
    )
    n_a = classify_futu_us_k1m_currentness(
        "2026-10-05 16:00:00", observed_at_utc=observed, market_state="PRE_MARKET_BEGIN"
    )

    assert summarize_futu_k1m_currentness({"AMD": passed, "NVDA": passed}) == "PASS"
    assert summarize_futu_k1m_currentness({"AMD": passed, "NVDA": stale}) == "FAIL"
    assert summarize_futu_k1m_currentness({"AMD": n_a, "NVDA": n_a}) == "NOT_APPLICABLE"
    assert summarize_futu_k1m_currentness({"AMD": passed, "NVDA": n_a}) == "UNKNOWN"
    assert summarize_futu_k1m_currentness({}) == "UNKNOWN"


def test_naive_observation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        classify_futu_us_k1m_currentness(
            "2026-10-06 09:35:00",
            observed_at_utc=datetime(2026, 10, 6, 13, 35),
            market_state="MORNING",
        )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("MORNING", "regular"),
        ("AFTERNOON", "regular"),
        ("PRE_MARKET_BEGIN", "premarket"),
        ("PRE_MARKET_END", "premarket"),
        ("AFTER_HOURS_BEGIN", "afterhours"),
        ("AFTER_HOURS_END", "afterhours"),
        ("OVERNIGHT", "overnight"),
        ("CLOSED", "closed"),
        ("WAITING_OPEN", "closed"),
        ("NONE", "closed"),
        ("SOMETHING_NEW", "unknown"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_futu_market_state_maps_to_cache_session_without_guessing(state, expected):
    assert futu_us_market_state_to_session(state) == expected


def test_interval_start_clock_skew_budget_is_explicit():
    result = classify_futu_us_k1m_currentness(
        "2026-10-06 09:36:00",
        observed_at_utc=datetime(2026, 10, 6, 13, 34, 56, tzinfo=timezone.utc),
        market_state="MORNING",
    )

    assert result.status == "PASS"
    assert result.reason == "K1M_INTERVAL_START_WITHIN_CLOCK_SKEW"
    assert result.age_seconds == 0
    assert result.end_offset_seconds == -64


def test_negative_interval_start_skew_budget_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        classify_futu_us_k1m_currentness(
            "2026-10-06 09:36:00",
            observed_at_utc=datetime(2026, 10, 6, 13, 35, tzinfo=timezone.utc),
            market_state="MORNING",
            max_interval_start_skew_seconds=-1,
        )
