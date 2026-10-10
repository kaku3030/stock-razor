"""Tests for deriving the TickFlow continuity gate without manual override."""
from datetime import datetime, timedelta, timezone

from src.services.tickflow_continuity_audit import TickflowObservation
from src.services.tickflow_continuity_shadow_adapter import (
    apply_tickflow_continuity_evidence,
)


NOW = datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc)


def payload():
    return {
        "schema": "stock_razor_tickflow_shadow_observation_v0_1",
        "provider": "TICKFLOW_SDK",
        "market": "CN",
        "source": "DESKTOP_TICKFLOW",
        "symbol": "159611.SZ",
        "timeframe": "15m",
        "reachable": "PASS",
        "process_healthy": "PASS",
        "entitlement_qualified": "PASS",
        "freshness_qualified": "PASS",
        "continuity_qualified": "UNKNOWN",
        "completeness_qualified": "PASS",
        "correctness_qualified": "PASS",
        "source_progress_qualified": "PASS",
        "crosscheck_status": "UNKNOWN",
        "latency_ms": 100.0,
        "source_age_ms": 100.0,
    }


def observations(*values):
    return tuple(
        TickflowObservation(
            sequence=sequence,
            observed_at=NOW - timedelta(seconds=age),
        )
        for sequence, age in values
    )


def test_passed_audit_derives_pass_and_latest_metadata():
    result = apply_tickflow_continuity_evidence(
        payload(), observations((10, 3), (11, 2), (12, 1)),
        now_utc=NOW, max_age_seconds=5,
    )
    assert result.audit.status.value == "PASS"
    assert result.payload["continuity_qualified"] == "PASS"
    assert result.payload["sequence"] == 12
    assert result.payload["observed_at_utc"] == "2026-10-10T12:59:59+00:00"


def test_failed_audit_derives_fail_not_unknown_or_pass():
    result = apply_tickflow_continuity_evidence(
        payload(), observations((10, 3), (12, 1)),
        now_utc=NOW, max_age_seconds=5,
    )
    assert result.audit.status.value == "BLOCKED"
    assert result.payload["continuity_qualified"] == "BLOCKED"
