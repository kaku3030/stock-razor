from datetime import datetime, timezone

import pytest

from src.services.provider_lifecycle import (
    ProviderHealthState,
    ProviderRuntimeIngestError,
    ProviderRuntimeObserver,
    build_alpaca_observation_from_runtime_events,
    ingest_alpaca_runtime_events,
)


SHA = "9e92bb3cf6c3ddff179bb03302fad420f80aaff4"


def event(
    event_type,
    *,
    event_at="2026-10-08T00:10:05+00:00",
    owner_identity="alpaca-owner-1",
    runtime_generation=0,
    feed="iex",
    **extra,
):
    payload = {
        "event_type": event_type,
        "event_at": event_at,
        "owner_identity": owner_identity,
        "runtime_generation": runtime_generation,
        "provider_type": "alpaca",
        "feed": feed,
        "ack_status": "UNKNOWN",
        "ack_evidence": "SDK_registration_return_only",
        "entitlement_status": "UNKNOWN",
        "entitlement_source": "EXTERNAL_ACCOUNT_EVIDENCE_REQUIRED",
    }
    payload.update(extra)
    return payload


def test_registration_and_worker_liveness_do_not_promote_provider_health():
    observation = build_alpaca_observation_from_runtime_events(
        [
            event("subscription_registered", symbols=["NVDA"]),
            event(
                "stream_worker_started",
                event_at="2026-10-08T00:10:06+00:00",
                worker_status="RUNNING",
                symbols=["NVDA"],
            ),
        ],
        repo_sha=SHA,
    )
    assert observation.provider_id == "alpaca"
    assert observation.fields["health_state"].value is ProviderHealthState.UNKNOWN
    assert observation.fields["failure_reason"].value is None
    assert "last_success" not in observation.fields
    assert "latency_ms" not in observation.fields
    assert "freshness_ms" not in observation.fields


def test_sip_feed_is_identity_not_entitlement_evidence():
    observation = build_alpaca_observation_from_runtime_events(
        [
            event(
                "subscription_registered",
                feed="sip",
                symbols=["NVDA"],
            )
        ],
        repo_sha=SHA,
    )
    capabilities = observation.fields["capabilities"].value
    assert capabilities["feed"] == "sip"
    assert capabilities["entitlement_status"] == "UNKNOWN"
    assert capabilities["entitlement_source"] == "EXTERNAL_ACCOUNT_EVIDENCE_REQUIRED"
    assert observation.fields["health_state"].value is ProviderHealthState.UNKNOWN


@pytest.mark.parametrize(
    "override",
    [
        {"entitlement_status": "GRANTED"},
        {"entitlement_status": "SIP"},
        {"ack_status": "ACKED"},
        {"entitlement_source": "SDK"},
        {"ack_evidence": "THREAD_RUNNING"},
    ],
)
def test_adapter_events_cannot_promote_ack_or_entitlement(override):
    with pytest.raises(ProviderRuntimeIngestError):
        build_alpaca_observation_from_runtime_events(
            [event("subscription_registered", **override)],
            repo_sha=SHA,
        )


def test_stream_worker_error_degrades_without_claiming_provider_failed():
    observation = build_alpaca_observation_from_runtime_events(
        [
            event("subscription_registered", symbols=["NVDA"]),
            event(
                "stream_worker_started",
                event_at="2026-10-08T00:10:06+00:00",
                worker_status="RUNNING",
                symbols=["NVDA"],
            ),
            event(
                "stream_worker_error",
                event_at="2026-10-08T00:10:07+00:00",
                stream_error_type="RuntimeError",
                worker_status="FAILED",
                symbols=["NVDA"],
            ),
            event(
                "worker_terminated",
                event_at="2026-10-08T00:10:08+00:00",
                worker_status="TERMINATED",
                symbols=["NVDA"],
            ),
        ],
        repo_sha=SHA,
    )
    assert observation.fields["health_state"].value is ProviderHealthState.DEGRADED
    assert observation.fields["failure_reason"].value == (
        "ALPACA_STREAM_WORKER_ERROR:RuntimeError"
    )
    assert observation.fields["last_failure"].value == datetime(
        2026, 10, 8, 0, 10, 7, tzinfo=timezone.utc
    )


def test_successful_shutdown_clears_current_failure_but_keeps_last_failure():
    observation = build_alpaca_observation_from_runtime_events(
        [
            event(
                "stream_worker_error",
                event_at="2026-10-08T00:10:07+00:00",
                stream_error_type="RuntimeError",
                worker_status="FAILED",
            ),
            event(
                "stop_requested",
                event_at="2026-10-08T00:10:08+00:00",
                runtime_generation=1,
                shutdown_status="REQUESTED",
                owner_status="RETAINED",
            ),
            event(
                "shutdown_completed",
                event_at="2026-10-08T00:10:09+00:00",
                runtime_generation=1,
                shutdown_status="SUCCEEDED",
                owner_status="CLEARED",
            ),
            event(
                "owner_cleared",
                event_at="2026-10-08T00:10:10+00:00",
                runtime_generation=1,
                shutdown_status="SUCCEEDED",
                owner_status="CLEARED",
            ),
        ],
        repo_sha=SHA,
    )
    assert observation.fields["health_state"].value is ProviderHealthState.UNKNOWN
    assert observation.fields["failure_reason"].value is None
    assert observation.fields["last_failure"].value == datetime(
        2026, 10, 8, 0, 10, 7, tzinfo=timezone.utc
    )


def test_shutdown_failure_is_negative_runtime_evidence():
    observation = build_alpaca_observation_from_runtime_events(
        [
            event(
                "stop_requested",
                runtime_generation=1,
                shutdown_status="REQUESTED",
                owner_status="RETAINED",
            ),
            event(
                "shutdown_failed",
                event_at="2026-10-08T00:10:06+00:00",
                runtime_generation=1,
                shutdown_status="FAILED",
                owner_status="RETAINED",
            ),
            event(
                "owner_retained",
                event_at="2026-10-08T00:10:07+00:00",
                runtime_generation=1,
                shutdown_status="FAILED",
                owner_status="RETAINED",
            ),
        ],
        repo_sha=SHA,
    )
    assert observation.fields["health_state"].value is ProviderHealthState.DEGRADED
    assert observation.fields["failure_reason"].value == "ALPACA_OWNER_RETAINED"
    assert observation.fields["last_failure"].value == datetime(
        2026, 10, 8, 0, 10, 7, tzinfo=timezone.utc
    )


def test_provenance_uses_owner_runtime_and_exact_repo_sha():
    observation = build_alpaca_observation_from_runtime_events(
        [
            event(
                "subscription_registered",
                runtime_generation=3,
                feed="iex",
            )
        ],
        repo_sha=SHA,
    )
    evidence = observation.fields["capabilities"].provenance
    assert evidence.source == "alpaca_adapter_runtime_events"
    assert evidence.runtime_id == "alpaca-owner-1"
    assert evidence.repo_sha == SHA
    assert evidence.observed_at == datetime(
        2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc
    )
    assert evidence.evidence_id == "alpaca:alpaca-owner-1:3:capabilities"


@pytest.mark.parametrize(
    ("events", "match"),
    [
        ([], "must not be empty"),
        (
            [event("subscription_registered", provider_type="other")],
            "provider_type must be alpaca",
        ),
        (
            [
                event("subscription_registered"),
                event(
                    "stream_worker_started",
                    owner_identity="alpaca-owner-2",
                    event_at="2026-10-08T00:10:06+00:00",
                ),
            ],
            "one owner_identity",
        ),
        (
            [
                event("subscription_registered", feed="iex"),
                event(
                    "stream_worker_started",
                    feed="sip",
                    event_at="2026-10-08T00:10:06+00:00",
                ),
            ],
            "one feed",
        ),
        (
            [
                event(
                    "subscription_registered",
                    event_at="2026-10-08T00:10:07+00:00",
                ),
                event(
                    "stream_worker_started",
                    event_at="2026-10-08T00:10:06+00:00",
                ),
            ],
            "event_at values must be non-decreasing",
        ),
        (
            [
                event("subscription_registered", runtime_generation=2),
                event(
                    "stream_worker_started",
                    runtime_generation=1,
                    event_at="2026-10-08T00:10:06+00:00",
                ),
            ],
            "runtime_generation must be non-decreasing",
        ),
    ],
)
def test_alpaca_event_stream_identity_is_fail_closed(events, match):
    with pytest.raises(ProviderRuntimeIngestError, match=match):
        build_alpaca_observation_from_runtime_events(events, repo_sha=SHA)


def test_unsupported_event_type_and_feed_are_rejected():
    with pytest.raises(ProviderRuntimeIngestError, match="event_type"):
        build_alpaca_observation_from_runtime_events(
            [event("ready")],
            repo_sha=SHA,
        )
    with pytest.raises(ProviderRuntimeIngestError, match="feed"):
        build_alpaca_observation_from_runtime_events(
            [event("subscription_registered", feed="premium")],
            repo_sha=SHA,
        )


def test_uppercase_repo_sha_is_rejected_not_normalized():
    with pytest.raises(ProviderRuntimeIngestError, match="lowercase git SHA"):
        build_alpaca_observation_from_runtime_events(
            [event("subscription_registered")],
            repo_sha=SHA.upper(),
        )


def test_end_to_end_ingest_uses_fallback_registry_identity():
    snapshot = ingest_alpaca_runtime_events(
        ProviderRuntimeObserver(),
        [event("subscription_registered", feed="iex")],
        repo_sha=SHA,
    )
    assert snapshot.record.provider_id == "alpaca"
    assert snapshot.record.role.value == "FALLBACK"
    assert snapshot.record.health_state is ProviderHealthState.UNKNOWN
    assert snapshot.record.credential_status == "UNKNOWN"
    assert snapshot.record.freshness_ms is None
    assert snapshot.record.latency_ms is None
