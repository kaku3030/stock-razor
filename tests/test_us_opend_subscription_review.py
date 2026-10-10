"""Offline tests: review is bounded, deterministic and never mutates OpenD."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.services.ai_monitor.watch_universe import (
    ActiveWatchUniverse, WatchSource,
)
from src.services.ai_monitor.opend_subscription_review import (
    review_us_opend_subscription_capacity,
)

NOW = datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)


def universe():
    w = ActiveWatchUniverse()
    w.activate(market="us", symbol="US.TSLA", source=WatchSource.RADAR,
               activated_at=NOW)
    w.activate(market="us", symbol="US.AMD", source=WatchSource.PORTFOLIO,
               activated_at=NOW)
    w.activate(market="us", symbol="US.NVDA", source=WatchSource.USER_PINNED,
               activated_at=NOW)
    w.activate(market="us", symbol="US.AMD", source=WatchSource.RADAR,
               activated_at=NOW)
    w.activate(market="cn", symbol="159611.SZ", source=WatchSource.PORTFOLIO,
               activated_at=NOW)
    return w.snapshot(generated_at=NOW)


def review(snapshot=None, **overrides):
    kwargs = {
        "subscribed_symbols": ["US.QQQ"], "quota_verified": True,
        "total_used": 8, "remain": 12, "now_utc": NOW,
        "quota_observed_at_utc": NOW,
    }
    kwargs.update(overrides)
    return review_us_opend_subscription_capacity(snapshot or universe(), **kwargs)


def test_prioritize_portfolio_pins_then_radar_without_provider_mutation():
    result = review()
    assert result["status"] == "REVIEW_ONLY"
    assert [(x["symbol"], x["priority"]) for x in result["candidates_for_review"]] == [
        ("US.AMD", "PORTFOLIO"), ("US.NVDA", "USER_PINNED"),
        ("US.TSLA", "RADAR")]
    assert result["provider_requests"] == 0
    assert result["provider_mutations"] == 0
    assert result["subscription_changes"] == "NONE"
    assert result["execution_permission"] == "BLOCKED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["subtype_entitlement"] == "NOT_VERIFIED"


def test_already_subscribed_symbols_are_excluded():
    result = review(subscribed_symbols=["US.AMD", "US.NVDA"])
    assert [x["symbol"] for x in result["candidates_for_review"]] == ["US.TSLA"]


def test_zero_remaining_still_never_suggests_executable_subscription():
    result = review(total_used=20, remain=0)
    assert result["status"] == "REVIEW_ONLY"
    assert result["aggregate_remaining"] == 0
    assert all(x["decision"] == "MANUAL_QUOTA_AND_ENTITLEMENT_REVIEW_REQUIRED"
               for x in result["candidates_for_review"])


def test_unverified_quota_is_blocked():
    for options in ({"quota_verified": False}, {"remain": None},
                    {"total_used": -1}, {"remain": True}):
        result = review(**options)
        assert result["status"] == "BLOCKED"
        assert result["candidates_for_review"] == []


def test_stale_snapshot_is_blocked():
    old = universe()
    from src.services.ai_monitor.watch_universe import WatchUniverseSnapshot
    stale = WatchUniverseSnapshot(
        generated_at=NOW - timedelta(minutes=10), watches=old.watches)
    assert review(stale)["reason"] == "STALE_OR_FUTURE_WATCH_SNAPSHOT"


def test_bad_symbol_and_review_limit_fail_closed():
    assert review(subscribed_symbols=["NOT.A.TICKER"])["status"] == "BLOCKED"
    assert review(max_review=0)["status"] == "BLOCKED"
    assert review(max_review=2)["truncated"] is True


def test_no_opend_sdk_calls_or_subscribe_execution():
    source = (Path(__file__).resolve().parents[1] /
              "src/services/ai_monitor/opend_subscription_review.py").read_text(
                  encoding="utf-8")
    assert "import futu" not in source
    assert "import requests" not in source
    assert ".subscribe(" not in source
    assert ".unsubscribe(" not in source
    assert "query_subscription(" not in source


def test_missing_or_stale_quota_observation_fails_closed():
    assert review(quota_observed_at_utc=None)["reason"] == "QUOTA_OBSERVATION_TIMESTAMP_REQUIRED"
    assert review(quota_observed_at_utc=NOW - timedelta(minutes=3))["reason"] == "STALE_OR_FUTURE_QUOTA_OBSERVATION"
    assert review(quota_observed_at_utc=NOW + timedelta(minutes=3))["reason"] == "STALE_OR_FUTURE_QUOTA_OBSERVATION"
    assert review(quota_observed_at_utc=NOW.replace(tzinfo=None))["reason"] == "QUOTA_OBSERVATION_TIMESTAMP_REQUIRED"


def test_fresh_quota_age_is_explicit():
    result = review(quota_observed_at_utc=NOW - timedelta(seconds=30))
    assert result["quota_observation_age_seconds"] == 30
    assert result["subscription_changes"] == "NONE"
