from datetime import datetime, timezone

import pytest

from src.services.provider_lifecycle import (
    ProviderHealthState,
    ProviderRuntimeIngestError,
    ProviderRuntimeObserver,
    build_moomoo_opend_observation_from_livefeed_heartbeat,
    ingest_moomoo_opend_livefeed_heartbeat,
)


SHA = "d9638dda99063beaa15841a9771591e4e396c2b3"


def heartbeat(**overrides):
    payload = {
        "type": "us_opend_livefeed_heartbeat",
        "runtime_instance_id": "cloud-opend-1",
        "repo_sha": SHA,
        "host_id": "aws-host-1",
        "sequence": 7,
        "emitted_at_utc": "2026-10-08T00:10:05+00:00",
        "symbols": ["US.AMD", "US.NVDA", "US.TSLA", "US.AAPL", "US.QQQ"],
        "subscribed": ["US.AMD", "US.NVDA", "US.TSLA", "US.AAPL", "US.QQQ"],
        "controller_lifecycle": "CONNECTED",
        "controller_failure_class": "UNKNOWN",
        "controller_findings_tail": [],
        "event_count": 25,
        "accepted_event_count": 30,
        "last_push_utc": "2026-10-08T00:10:04+00:00",
        "market_state_us": "MORNING",
        "market_state_evidence": "PASS",
        "canonical_snapshot_export": {
            "status": "PASS",
            "error": None,
        },
        "delivery_mode": "REALTIME",
        "bar_closure": "PROVEN",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    payload.update(overrides)
    return payload


def test_connected_realtime_heartbeat_does_not_promote_healthy():
    observation = build_moomoo_opend_observation_from_livefeed_heartbeat(
        heartbeat()
    )
    assert observation.provider_id == "moomoo_opend"
    assert observation.fields["health_state"].value is ProviderHealthState.UNKNOWN
    assert "freshness_ms" not in observation.fields
    assert "latency_ms" not in observation.fields


def test_runtime_provenance_is_exact_and_field_specific():
    observation = build_moomoo_opend_observation_from_livefeed_heartbeat(
        heartbeat()
    )
    evidence = observation.fields["health_state"].provenance
    assert evidence.observed_at == datetime(
        2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc
    )
    assert evidence.source == "us_opend_livefeed_heartbeat"
    assert evidence.runtime_id == "cloud-opend-1"
    assert evidence.repo_sha == SHA
    assert evidence.evidence_id == "us-opend:cloud-opend-1:7:health_state"


def test_last_push_is_success_receipt_time_not_freshness():
    observation = build_moomoo_opend_observation_from_livefeed_heartbeat(
        heartbeat()
    )
    assert observation.fields["last_success"].value == datetime(
        2026, 10, 8, 0, 10, 4, tzinfo=timezone.utc
    )
    assert "freshness_ms" not in observation.fields


def test_no_data_events_do_not_invent_last_success():
    observation = build_moomoo_opend_observation_from_livefeed_heartbeat(
        heartbeat(event_count=0, accepted_event_count=3, last_push_utc=None)
    )
    assert "last_success" not in observation.fields


@pytest.mark.parametrize(
    ("lifecycle", "expected"),
    [
        ("FAILED", ProviderHealthState.FAILED),
        ("DEGRADED", ProviderHealthState.DEGRADED),
        ("RECONNECTING", ProviderHealthState.DEGRADED),
        ("DISCONNECTED", ProviderHealthState.DEGRADED),
    ],
)
def test_negative_transport_states_can_degrade_provider_health(lifecycle, expected):
    observation = build_moomoo_opend_observation_from_livefeed_heartbeat(
        heartbeat(
            controller_lifecycle=lifecycle,
            controller_findings_tail=["transport-finding"],
        )
    )
    assert observation.fields["health_state"].value is expected
    assert observation.fields["failure_reason"].value == "transport-finding"
    assert observation.fields["last_failure"].value == datetime(
        2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc
    )


def test_recovered_connected_state_clears_current_failure_reason_only():
    observer = ProviderRuntimeObserver()
    failed = heartbeat(
        sequence=7,
        emitted_at_utc="2026-10-08T00:10:05+00:00",
        controller_lifecycle="FAILED",
        controller_findings_tail=["transport-down"],
    )
    recovered = heartbeat(
        sequence=8,
        emitted_at_utc="2026-10-08T00:10:10+00:00",
        last_push_utc="2026-10-08T00:10:09+00:00",
        controller_lifecycle="CONNECTED",
        controller_findings_tail=[],
    )
    ingest_moomoo_opend_livefeed_heartbeat(observer, failed)
    snapshot = ingest_moomoo_opend_livefeed_heartbeat(observer, recovered)
    assert snapshot.record.health_state is ProviderHealthState.UNKNOWN
    assert snapshot.record.failure_reason is None
    assert snapshot.record.last_failure == datetime(
        2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc
    )


def test_capability_facts_preserve_admission_separation_and_are_read_only():
    observer = ProviderRuntimeObserver()
    snapshot = ingest_moomoo_opend_livefeed_heartbeat(observer, heartbeat())
    capabilities = snapshot.record.capabilities
    assert capabilities["delivery_mode"] == "REALTIME"
    assert capabilities["bar_closure"] == "PROVEN"
    assert capabilities["radar_admission"] == "BLOCKED"
    assert capabilities["live_trade"] is False
    with pytest.raises(TypeError):
        capabilities["radar_admission"] = "PASS"


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"live_trade": True},
        {"radar_admission": "PASS"},
        {"repo_sha": "abc"},
        {"type": "wrong"},
        {"sequence": 0},
        {"accepted_event_count": 1, "event_count": 2},
    ],
)
def test_governance_and_identity_violations_are_rejected(bad_payload):
    with pytest.raises(ProviderRuntimeIngestError):
        build_moomoo_opend_observation_from_livefeed_heartbeat(
            heartbeat(**bad_payload)
        )


def test_uppercase_repo_sha_is_rejected_not_normalized():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="lowercase git SHA",
    ):
        build_moomoo_opend_observation_from_livefeed_heartbeat(
            heartbeat(repo_sha=SHA.upper())
        )


def test_live_controller_state_is_rejected_by_current_contract():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="controller_lifecycle LIVE is forbidden",
    ):
        build_moomoo_opend_observation_from_livefeed_heartbeat(
            heartbeat(controller_lifecycle="LIVE")
        )


def test_naive_heartbeat_timestamp_is_rejected():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="emitted_at_utc must be timezone-aware",
    ):
        build_moomoo_opend_observation_from_livefeed_heartbeat(
            heartbeat(emitted_at_utc="2026-10-08T00:10:05")
        )


def test_last_push_after_heartbeat_is_rejected():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="last_push_utc must not be after emitted_at_utc",
    ):
        build_moomoo_opend_observation_from_livefeed_heartbeat(
            heartbeat(last_push_utc="2026-10-08T00:10:06+00:00")
        )


def test_canonical_export_failure_is_context_not_provider_failure():
    observation = build_moomoo_opend_observation_from_livefeed_heartbeat(
        heartbeat(
            canonical_snapshot_export={
                "status": "BLOCKED",
                "error": "CanonicalWriteError",
            }
        )
    )
    assert observation.fields["health_state"].value is ProviderHealthState.UNKNOWN
    capabilities = observation.fields["capabilities"].value
    assert capabilities["canonical_snapshot_status"] == "BLOCKED"
    assert capabilities["canonical_snapshot_error"] == "CanonicalWriteError"


def test_end_to_end_ingest_uses_static_registry_identity():
    snapshot = ingest_moomoo_opend_livefeed_heartbeat(
        ProviderRuntimeObserver(),
        heartbeat(),
    )
    assert snapshot.record.provider_id == "moomoo_opend"
    assert snapshot.record.role.value == "PRIMARY"
    assert snapshot.record.fallback_provider == "alpaca"
