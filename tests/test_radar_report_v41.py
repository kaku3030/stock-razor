from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from data_provider.radar_report_v41 import TIMEFRAMES, build_report

NOW = datetime(2026, 10, 19, 2, 0, tzinfo=timezone.utc)
RECEIVED = NOW
COMPLETED = NOW + timedelta(milliseconds=90)
TIMINGS = {
    "windows_fetch_ms": 25, "aws_fetch_ms": 31, "validation_ms": 2,
    "technical_analysis_ms": 15, "radar_scan_ms": 9,
    "report_generation_ms": 3, "end_to_end_ms": 90,
}


def _build_report(market, symbol, evidence, **kwargs):
    return build_report(
        market, symbol, evidence, received_at_utc=RECEIVED.isoformat(),
        report_completed_at_utc=COMPLETED.isoformat(), **kwargs,
    )


def _endpoint(market: str, name: str) -> dict:
    provider = "TickFlow" if market == "CN" else "OpenD"
    bars = {}
    for frame in TIMEFRAMES:
        stamp = NOW - timedelta(minutes=1)
        bars[frame] = {
            "bar_end_utc": stamp.isoformat(), "open": 10.0, "high": 12.0,
            "low": 9.0, "close": 11.0, "volume": 100,
            "is_closed": True, "continuity": "PASS",
            "freshness_checked_at_utc": NOW.isoformat(),
            "age_seconds": 60, "max_age_seconds": 120,
        }
    return {
        "provider": provider, "endpoint_id": name,
        "permission_status": "VERIFIED", "fallback_from": None,
        "market_session": {"state": "OPEN", "timezone": "America/New_York" if market == "US" else "Asia/Shanghai", "session_date": "2026-10-19"},
        "provenance": {
            "endpoint": f"{name.lower()}_native", "repo_sha": "a" * 40,
            "runtime_sha": "b" * 40, "observed_at_utc": NOW.isoformat(),
            "request_latency_ms": 10.5,
        },
        "bars": bars,
    }


def _evidence(market="US"):
    return {"WINDOWS": _endpoint(market, "WINDOWS"), "AWS": _endpoint(market, "AWS")}


@pytest.mark.parametrize("market", ["CN", "US"])
def test_valid_dual_endpoint_five_timeframe_report_is_research_only(market):
    report = _build_report(
        market, "600000" if market == "CN" else "AAPL", _evidence(market),
        holdings=[{"symbol": "600000" if market == "CN" else "AAPL", "quantity": 10, "quantity_as_of_utc": NOW.isoformat(), "verification": "VERIFIED", "source": "portfolio_snapshot"}],
        opportunities=[{"symbol": "AAPL", "rank": 1}],
        conditional_plans=[{"symbol": "AAPL", "entry_condition": "reclaim"}],
        timings=TIMINGS,
    )
    assert report["status"] == "PASS_RESEARCH_ONLY"
    assert report["timeframes"] == list(TIMEFRAMES)
    assert report["provider"] == ("TickFlow" if market == "CN" else "OpenD")
    assert list(report["holdings"]) == ["status", "items"]
    assert report["holdings"]["status"] == "VERIFIED"
    assert report["opportunities"] and report["conditional_plans"]
    assert report["execution"] == "NONE"
    assert report["safety"]["live_trade"] is False
    assert report["safety"]["radar_admission"] == "BLOCKED"


@pytest.mark.parametrize("defect,reason", [
    ("missing", "AWS_1H_MISSING"),
    ("stale", "WINDOWS_1m_BAR_STALE_OR_FRESHNESS_INVALID"),
    ("open", "AWS_5m_BAR_NOT_CLOSED"),
    ("ohlc", "WINDOWS_15m_BAR_OHLC_INVALID"),
    ("mismatch", "DUAL_ENDPOINT_D1_DISAGREEMENT"),
    ("fallback", "AWS_PROVIDER_FALLBACK_PROHIBITED"),
    ("lying_age", "WINDOWS_1m_BAR_STALE_OR_FRESHNESS_INVALID"),
])
def test_dual_endpoint_defects_fail_closed_and_remove_candidates(defect, reason):
    evidence = _evidence()
    if defect == "missing":
        del evidence["AWS"]["bars"]["1H"]
    elif defect == "stale":
        evidence["WINDOWS"]["bars"]["1m"].update(age_seconds=121, max_age_seconds=120)
    elif defect == "open":
        evidence["AWS"]["bars"]["5m"]["is_closed"] = False
    elif defect == "ohlc":
        evidence["WINDOWS"]["bars"]["15m"].update(low=13.0)
    elif defect == "mismatch":
        evidence["AWS"]["bars"]["D1"]["close"] = 11.5
    elif defect == "lying_age":
        evidence["WINDOWS"]["bars"]["1m"].update(
            bar_end_utc=(NOW - timedelta(minutes=30)).isoformat(), age_seconds=60
        )
    else:
        evidence["AWS"]["fallback_from"] = "provider_fallback"
    report = _build_report(
        "US", "AAPL", evidence, opportunities=[{"symbol": "MSFT"}],
        conditional_plans=[{"symbol": "AAPL"}], timings=TIMINGS,
    )
    assert report["status"] == "BLOCKED"
    assert report["data_acceptance"] == "NOT_VERIFIED"
    assert reason in report["feedback"]["reasons"]
    assert report["opportunities"] == []
    assert report["conditional_plans"] == []
    assert report["safety"]["radar_admission"] == "BLOCKED"


def test_provider_and_endpoint_must_be_exactly_the_protocol_pair():
    evidence = _evidence("CN")
    evidence["WINDOWS"]["provider"] = "Eastmoney"
    evidence["AWS"]["endpoint_id"] = "OTHER"
    result = _build_report("CN", "600000", evidence, timings=TIMINGS)
    assert "WINDOWS_PROVIDER_NOT_ALLOWED" in result["feedback"]["reasons"]
    assert "AWS_ENDPOINT_ID_MISMATCH" in result["feedback"]["reasons"]


def test_invalid_symbol_is_not_reflected_in_report_or_feedback_key():
    report = _build_report("US", "api_key=DO_NOT_ECHO", _evidence(), timings=TIMINGS)
    assert report["status"] == "BLOCKED"
    assert report["symbol"] == "UNKNOWN"
    assert "DO_NOT_ECHO" not in repr(report)


def test_malformed_bar_container_blocks_without_raising():
    evidence = _evidence()
    evidence["AWS"]["bars"] = []
    result = _build_report("US", "AAPL", evidence, timings=TIMINGS)
    assert result["status"] == "BLOCKED"
    assert "AWS_1m_MISSING" in result["feedback"]["reasons"]


def test_empty_holdings_are_not_misreported_as_verified():
    report = _build_report("US", "AAPL", _evidence(), holdings=[], timings=TIMINGS)
    assert report["holdings"]["status"] == "USER_REPORTED_OR_UNKNOWN"


def test_malicious_holding_values_do_not_crash_or_echo():
    report = _build_report(
        "US", "AAPL", _evidence(), timings=TIMINGS,
        holdings=[{"symbol": "api_key=PRIVATE", "quantity": 10**1000,
                   "quantity_as_of_utc": "not-a-time", "verification": "VERIFIED",
                   "source": "secret=SHOULD_NOT_ECHO"}],
    )
    assert report["holdings"]["status"] == "USER_REPORTED_OR_UNKNOWN"
    assert "SHOULD_NOT_ECHO" not in repr(report)
    assert "PRIVATE" not in repr(report)


@pytest.mark.parametrize("timings", [None, {}, {**TIMINGS, "end_to_end_ms": -1}, {**TIMINGS, "windows_fetch_ms": float("nan")}])
def test_unmeasured_or_invalid_phase_timing_blocks_report(timings):
    result = _build_report("US", "AAPL", _evidence(), timings=timings)
    assert result["status"] == "BLOCKED"
    assert "TIMING_FIELDS_INCOMPLETE" in result["feedback"]["reasons"]
    if timings and timings.get("end_to_end_ms") == -1:
        assert result["performance"]["end_to_end_ms"] == 90
    else:
        assert "NOT_MEASURED" in result["performance"].values()


def test_end_to_end_cannot_be_shorter_than_any_report_phase():
    timings = {**TIMINGS, "end_to_end_ms": 8}
    result = _build_report("US", "AAPL", _evidence(), timings=timings)
    assert result["status"] == "BLOCKED"
    assert "END_TO_END_TIMING_INCONSISTENT" in result["feedback"]["reasons"]


def test_report_receipt_and_completion_timestamps_are_required():
    result = build_report("US", "AAPL", _evidence(), timings=TIMINGS)
    assert result["status"] == "BLOCKED"
    assert "REPORT_TIME_WINDOW_INVALID" in result["feedback"]["reasons"]


def test_endpoint_market_sessions_must_align():
    evidence = _evidence()
    evidence["AWS"]["market_session"]["state"] = "AFTER_HOURS"
    result = _build_report("US", "AAPL", evidence, timings=TIMINGS)
    assert result["status"] == "BLOCKED"
    assert "DUAL_ENDPOINT_SESSION_DISAGREEMENT" in result["feedback"]["reasons"]


def test_dedupe_key_is_stable_for_same_acceptance_failure():
    evidence = _evidence()
    evidence["AWS"]["bars"].pop("D1")
    first = _build_report("US", "AAPL", evidence, timings=TIMINGS)
    second = _build_report("US", "AAPL", deepcopy(evidence), timings=TIMINGS)
    assert first["feedback"]["dedupe_key"] == second["feedback"]["dedupe_key"]


def test_raw_endpoint_payload_is_not_echoed_and_fallback_never_surfaces():
    evidence = _evidence()
    evidence["AWS"]["api_key"] = "secret=SHOULD_NOT_LEAK"
    evidence["WINDOWS"]["provider_payload"] = "raw provider response"
    evidence["AWS"]["fallback_from"] = "Yahoo"
    evidence["AWS"]["bars"]["1m"]["close"] = "password=ALSO_PRIVATE"
    report = _build_report("US", "AAPL", evidence, timings=TIMINGS)
    rendered = repr(report)
    assert "SHOULD_NOT_LEAK" not in rendered
    assert "raw provider response" not in rendered
    assert "ALSO_PRIVATE" not in rendered
    assert report["endpoint_evidence"]["AWS"]["fallback_from"] == "PRESENT"

