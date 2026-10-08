from datetime import datetime, timezone

import pytest

from src.services.tickflow_source_arbiter_shadow import (
    build_shadow_candidate,
    propose_tickflow_shadow,
)


def _payload(**overrides):
    value = {
        "schema": "stock_razor_tickflow_shadow_observation_v0_1",
        "provider": "TICKFLOW_SDK",
        "source": "DESKTOP_TICKFLOW",
        "market": "CN",
        "symbol": "600519.SH",
        "timeframe": "1m",
        "observed_at_utc": "2026-10-08T13:00:00+00:00",
        "latency_ms": 125.0,
        "source_age_ms": 250.0,
        "sequence": 7,
    }
    value.update(overrides)
    return value


def test_missing_qualification_stays_blocked():
    result = propose_tickflow_shadow(
        _payload(), now_utc=datetime(2026, 10, 8, 13, 1, tzinfo=timezone.utc), max_age_ms=1000,
    )
    assert result["decision"] == "BLOCKED"
    assert result["proposed_source"] is None
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_even_qualified_shadow_result_cannot_authorize_writes():
    payload = _payload(**{gate: "PASS" for gate in (
        "reachable", "process_healthy", "entitlement_qualified",
        "freshness_qualified", "continuity_qualified", "completeness_qualified",
        "correctness_qualified", "source_progress_qualified",
    )})
    result = propose_tickflow_shadow(
        payload, now_utc=datetime(2026, 10, 8, 13, 0, 1, tzinfo=timezone.utc), max_age_ms=1000,
    )
    assert result["decision"] == "SHADOW_PROPOSAL"
    assert result["proposed_source"] == "DESKTOP_TICKFLOW"
    assert result["canonical_write_authorized"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


@pytest.mark.parametrize("field,value", [
    ("schema", "wrong"), ("source", "CLOUD_TICKFLOW"), ("market", "US"),
    ("timeframe", "2m"), ("observed_at_utc", "2026-10-08T13:00:00"),
    ("latency_ms", -1), ("sequence", -1),
])
def test_malformed_or_unsafe_observation_is_rejected(field, value):
    with pytest.raises(ValueError):
        build_shadow_candidate(_payload(**{field: value}))


def test_raw_provider_payload_fields_are_not_needed_or_forwarded():
    candidate = build_shadow_candidate(_payload(price=123.45, api_key="secret-must-not-be-used"))
    assert candidate.source == "DESKTOP_TICKFLOW"
    assert not hasattr(candidate, "price")
