from datetime import datetime, timedelta, timezone

from data_provider.market_data_adapter import Bar
from src.services.live_feed.futu_k1m_closure_qualification import (
    FutuK1MClosureQualificationTracker,
    derive_futu_k1m_bar_closure_state,
    summarize_futu_k1m_closure_qualification,
)
from src.services.live_feed.futu_k1m_currentness import FutuK1MCurrentnessResult


BASE = datetime(2026, 10, 6, 14, 20, tzinfo=timezone.utc)


def currentness(boundary: datetime, *, status="PASS", reason="OK"):
    return FutuK1MCurrentnessResult(
        status=status,
        reason=reason,
        market_state="AFTERNOON",
        source_time_utc=boundary + timedelta(minutes=1),
        interval_start_utc=boundary,
        interval_end_utc=boundary + timedelta(minutes=1),
        observed_at_utc=boundary + timedelta(seconds=30),
        age_seconds=-30.0,
        end_offset_seconds=-30.0,
    )


def bar(
    boundary: datetime,
    *,
    symbol="US.AMD",
    provider="futu",
    feed="opend",
    closed=True,
    complete=True,
    source_timestamp=None,
):
    return Bar(
        symbol=symbol,
        market="us",
        asset_type="stock",
        timeframe="1m",
        bar_start=boundary - timedelta(minutes=1),
        bar_end=boundary,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000.0,
        provider=provider,
        source_timestamp=source_timestamp or boundary,
        received_at=boundary + timedelta(seconds=1),
        session="regular",
        is_closed=closed,
        is_complete=complete,
        feed=feed,
    )


def test_three_unique_consecutive_boundaries_prove_runtime_closure_evidence():
    tracker = FutuK1MClosureQualificationTracker(required_consecutive_boundaries=3)

    one = tracker.observe("US.AMD", currentness=currentness(BASE), latest_closed_bar=bar(BASE))
    two = tracker.observe(
        "US.AMD",
        currentness=currentness(BASE + timedelta(minutes=1)),
        latest_closed_bar=bar(BASE + timedelta(minutes=1)),
    )
    three = tracker.observe(
        "US.AMD",
        currentness=currentness(BASE + timedelta(minutes=2)),
        latest_closed_bar=bar(BASE + timedelta(minutes=2)),
    )

    assert one.status == "UNKNOWN"
    assert one.consecutive_boundaries == 1
    assert two.status == "UNKNOWN"
    assert two.consecutive_boundaries == 2
    assert three.status == "PASS"
    assert three.reason == "CONSECUTIVE_CLOSURE_BOUNDARIES_PROVEN"
    assert three.consecutive_boundaries == 3
    assert three.boundary_delta_seconds == 0.0
    assert three.can_promote is False
    assert three.bar_closure == "UNPROVEN"
    assert three.delivery_mode == "UNKNOWN"
    assert three.radar_admission == "BLOCKED"
    assert three.live_trade is False


def test_duplicate_heartbeat_does_not_increment_boundary_count():
    tracker = FutuK1MClosureQualificationTracker(required_consecutive_boundaries=3)
    first = tracker.observe("US.AMD", currentness=currentness(BASE), latest_closed_bar=bar(BASE))
    duplicate = tracker.observe("US.AMD", currentness=currentness(BASE), latest_closed_bar=bar(BASE))
    assert first.consecutive_boundaries == 1
    assert duplicate.consecutive_boundaries == 1


def test_gap_resets_consecutive_evidence_without_false_pass():
    tracker = FutuK1MClosureQualificationTracker(required_consecutive_boundaries=3)
    tracker.observe("US.AMD", currentness=currentness(BASE), latest_closed_bar=bar(BASE))
    result = tracker.observe(
        "US.AMD",
        currentness=currentness(BASE + timedelta(minutes=2)),
        latest_closed_bar=bar(BASE + timedelta(minutes=2)),
    )
    assert result.status == "UNKNOWN"
    assert result.reason == "BOUNDARY_GAP_RESET"
    assert result.consecutive_boundaries == 1


def test_regression_fails_closed_and_resets_state():
    tracker = FutuK1MClosureQualificationTracker(required_consecutive_boundaries=3)
    tracker.observe(
        "US.AMD",
        currentness=currentness(BASE + timedelta(minutes=1)),
        latest_closed_bar=bar(BASE + timedelta(minutes=1)),
    )
    result = tracker.observe("US.AMD", currentness=currentness(BASE), latest_closed_bar=bar(BASE))
    assert result.status == "FAIL"
    assert result.reason == "BOUNDARY_REGRESSION"
    assert result.consecutive_boundaries == 0


def test_forming_start_must_equal_latest_canonical_closed_end():
    tracker = FutuK1MClosureQualificationTracker()
    result = tracker.observe(
        "US.AMD",
        currentness=currentness(BASE),
        latest_closed_bar=bar(BASE - timedelta(minutes=1)),
    )
    assert result.status == "FAIL"
    assert result.reason == "FORMING_START_DOES_NOT_MATCH_LATEST_CLOSED_END"
    assert result.boundary_delta_seconds == -60.0


def test_bar_contract_must_be_closed_complete_futu_opend_and_source_end_labeled():
    cases = [
        (bar(BASE, closed=False), "CANONICAL_BAR_NOT_CLOSED"),
        (bar(BASE, complete=False), "CANONICAL_BAR_NOT_COMPLETE"),
        (bar(BASE, provider="other"), "CANONICAL_PROVIDER_MISMATCH"),
        (bar(BASE, feed="other"), "CANONICAL_FEED_MISMATCH"),
        (
            bar(BASE, source_timestamp=BASE - timedelta(minutes=1)),
            "CANONICAL_SOURCE_TIMESTAMP_MISMATCH",
        ),
    ]
    for candidate, reason in cases:
        tracker = FutuK1MClosureQualificationTracker()
        result = tracker.observe(
            "US.AMD",
            currentness=currentness(BASE),
            latest_closed_bar=candidate,
        )
        assert result.status == "FAIL"
        assert result.reason == reason


def test_waits_for_first_canonical_bar_without_inventing_closure():
    tracker = FutuK1MClosureQualificationTracker()
    result = tracker.observe("US.AMD", currentness=currentness(BASE), latest_closed_bar=None)
    assert result.status == "UNKNOWN"
    assert result.reason == "WAITING_FOR_FIRST_CANONICAL_CLOSED_BAR"
    assert result.consecutive_boundaries == 0


def test_currentness_fail_and_not_applicable_revoke_accumulated_evidence():
    tracker = FutuK1MClosureQualificationTracker(required_consecutive_boundaries=2)
    tracker.observe("US.AMD", currentness=currentness(BASE), latest_closed_bar=bar(BASE))
    fail = tracker.observe(
        "US.AMD",
        currentness=currentness(
            BASE + timedelta(minutes=1),
            status="FAIL",
            reason="K1M_STALE_DURING_REGULAR_SESSION",
        ),
        latest_closed_bar=bar(BASE + timedelta(minutes=1)),
    )
    assert fail.status == "FAIL"
    assert fail.consecutive_boundaries == 0

    tracker.observe(
        "US.AMD",
        currentness=currentness(BASE + timedelta(minutes=2)),
        latest_closed_bar=bar(BASE + timedelta(minutes=2)),
    )
    not_applicable = currentness(
        BASE + timedelta(minutes=3),
        status="NOT_APPLICABLE",
        reason="MARKET_NOT_REGULAR_SESSION",
    )
    result = tracker.observe(
        "US.AMD",
        currentness=not_applicable,
        latest_closed_bar=bar(BASE + timedelta(minutes=3)),
    )
    assert result.status == "NOT_APPLICABLE"
    assert result.consecutive_boundaries == 0


def test_symbol_states_are_independent():
    tracker = FutuK1MClosureQualificationTracker(required_consecutive_boundaries=2)
    tracker.observe("US.AMD", currentness=currentness(BASE), latest_closed_bar=bar(BASE))
    nvda = tracker.observe(
        "US.NVDA",
        currentness=currentness(BASE),
        latest_closed_bar=bar(BASE, symbol="US.NVDA"),
    )
    amd = tracker.observe(
        "US.AMD",
        currentness=currentness(BASE + timedelta(minutes=1)),
        latest_closed_bar=bar(BASE + timedelta(minutes=1)),
    )
    assert nvda.consecutive_boundaries == 1
    assert nvda.status == "UNKNOWN"
    assert amd.consecutive_boundaries == 2
    assert amd.status == "PASS"


def test_summary_is_fail_closed():
    tracker = FutuK1MClosureQualificationTracker(required_consecutive_boundaries=2)
    results = {}
    for symbol in ("US.AMD", "US.NVDA"):
        tracker.observe(
            symbol,
            currentness=currentness(BASE),
            latest_closed_bar=bar(BASE, symbol=symbol),
        )
        results[symbol] = tracker.observe(
            symbol,
            currentness=currentness(BASE + timedelta(minutes=1)),
            latest_closed_bar=bar(BASE + timedelta(minutes=1), symbol=symbol),
        )
    assert summarize_futu_k1m_closure_qualification(results) == "PASS"

    results["US.NVDA"] = tracker.observe(
        "US.NVDA",
        currentness=currentness(BASE + timedelta(minutes=2)),
        latest_closed_bar=bar(BASE + timedelta(minutes=1), symbol="US.NVDA"),
    )
    assert summarize_futu_k1m_closure_qualification(results) == "FAIL"



def test_top_level_bar_closure_promotes_only_when_both_summaries_pass():
    assert derive_futu_k1m_bar_closure_state(
        currentness_summary="PASS",
        closure_qualification_summary="PASS",
    ) == "PROVEN"

    for currentness_summary, closure_summary in [
        ("UNKNOWN", "PASS"),
        ("FAIL", "PASS"),
        ("NOT_APPLICABLE", "PASS"),
        ("PASS", "UNKNOWN"),
        ("PASS", "FAIL"),
        ("PASS", "NOT_APPLICABLE"),
        ("UNKNOWN", "UNKNOWN"),
        ("BOGUS", "PASS"),
        ("PASS", "BOGUS"),
    ]:
        assert derive_futu_k1m_bar_closure_state(
            currentness_summary=currentness_summary,
            closure_qualification_summary=closure_summary,
        ) == "UNPROVEN"
