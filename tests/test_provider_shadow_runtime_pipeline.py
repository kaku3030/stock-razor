from datetime import datetime, timedelta, timezone

import pytest

from src.services.provider_lifecycle import (
    ProviderHealthState,
    ProviderShadowRuntimePipeline,
)


T0 = datetime(2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc)
OPEND_SHA = "d9638dda99063beaa15841a9771591e4e396c2b3"
CN_SHA = "bd5d094f21c3421c41b65feba474c7ec46ecf2c1"
ALPACA_SHA = "9e92bb3cf6c3ddff179bb03302fad420f80aaff4"
PROBE_SHA = "ce62727b1d8f261112b17b7bb0290f6573119b41"


def heartbeat(**overrides):
    payload = {
        "type": "us_opend_livefeed_heartbeat",
        "runtime_instance_id": "cloud-opend-1",
        "repo_sha": OPEND_SHA,
        "host_id": "aws-host-1",
        "sequence": 7,
        "emitted_at_utc": "2026-10-08T00:10:05+00:00",
        "symbols": ["US.AMD", "US.NVDA"],
        "subscribed": ["US.AMD", "US.NVDA"],
        "controller_lifecycle": "CONNECTED",
        "controller_failure_class": "UNKNOWN",
        "controller_findings_tail": [],
        "event_count": 10,
        "accepted_event_count": 10,
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


def cn_fallback_snapshot():
    return {
        "schema": "stock_razor_cn_eastmoney_observation_v1",
        "repo_sha": CN_SHA,
        "runtime_instance_id": "cn-runtime-1",
        "sequence": 9,
        "emitted_at_utc": "2026-10-08T00:10:05+00:00",
        "host_id": "aws-cn-1",
        "status": "PASS",
        "symbols": {
            "159611": {
                "status": "PASS",
                "providers_used": ["tencent"],
                "timeframes": {
                    "15m": {
                        "status": "PASS",
                        "provider_used": "tencent",
                        "provider_lineage": "tencent",
                        "fallback_from": "eastmoney",
                        "fallback_reason": "RuntimeError",
                        "error": None,
                        "request_latency_ms": 12.5,
                        "currentness": "PROVEN",
                    }
                },
            }
        },
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "providers_used": ["tencent"],
        "provider_lineages": ["eastmoney", "tencent"],
        "intraday_timestamp_semantics_proven": True,
        "intraday_currentness_proven": True,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def alpaca_event(event_type, *, event_at, **extra):
    payload = {
        "event_type": event_type,
        "event_at": event_at,
        "owner_identity": "alpaca-owner-1",
        "runtime_generation": 0,
        "provider_type": "alpaca",
        "feed": "iex",
        "ack_status": "UNKNOWN",
        "ack_evidence": "SDK_registration_return_only",
        "entitlement_status": "UNKNOWN",
        "entitlement_source": "EXTERNAL_ACCOUNT_EVIDENCE_REQUIRED",
    }
    payload.update(extra)
    return payload


def negative_probe(**overrides):
    payload = {
        "schema": "stock_razor_provider_negative_probe_v1",
        "provider_id": "openai",
        "condition": "INSUFFICIENT_QUOTA",
        "observed_at_utc": "2026-10-08T00:10:05+00:00",
        "runtime_instance_id": "provider-probe-1",
        "repo_sha": PROBE_SHA,
        "probe_source": "secure_e2e_probe",
        "http_status": 429,
        "error_code": "insufficient_quota",
        "error_type": "ApiError",
        "research_only": True,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    payload.update(overrides)
    return payload


def test_opend_failure_then_recovery_keeps_state_and_builds_resolved_shadow_plan():
    pipeline = ProviderShadowRuntimePipeline()
    failed = pipeline.process_opend_heartbeat(
        heartbeat(
            controller_lifecycle="FAILED",
            controller_findings_tail=["transport-down"],
        ),
        now=T0,
    )
    recovered = pipeline.process_opend_heartbeat(
        heartbeat(
            sequence=8,
            emitted_at_utc="2026-10-08T00:10:10+00:00",
            last_push_utc="2026-10-08T00:10:09+00:00",
            controller_lifecycle="CONNECTED",
            controller_findings_tail=[],
        ),
        now=T0 + timedelta(seconds=5),
    )

    assert failed.provider_ids == ("moomoo_opend",)
    assert failed.transition_count == 1
    assert failed.planned_notification_count == 1
    assert failed.actual_notification_count == 0
    assert failed.shadow_results[0].notification_plans[0].structured_payload[
        "transition_state"
    ] == "OPEN"

    assert recovered.snapshots[0].record.health_state is ProviderHealthState.UNKNOWN
    assert recovered.transition_count == 1
    assert recovered.planned_notification_count == 1
    assert recovered.shadow_results[0].notification_plans[0].structured_payload[
        "transition_state"
    ] == "RESOLVED"


def test_cn_fallback_attributes_shadow_alert_only_to_degraded_eastmoney():
    cycle = ProviderShadowRuntimePipeline().process_cn_cloud_observation(
        cn_fallback_snapshot(),
        now=T0,
    )

    assert cycle.provider_ids == ("eastmoney", "tencent")
    assert cycle.transition_count == 1
    assert cycle.planned_notification_count == 1
    assert cycle.actual_notification_count == 0

    eastmoney, tencent = cycle.shadow_results
    assert [
        item.code for item in eastmoney.evaluation.transitions
    ] == ["RUNTIME_HEALTH_DEGRADED"]
    assert tencent.evaluation.transitions == ()
    assert tencent.notification_plans == ()


def test_alpaca_runtime_error_flows_to_shadow_warning_without_entitlement_claim():
    cycle = ProviderShadowRuntimePipeline().process_alpaca_runtime_events(
        [
            alpaca_event(
                "subscription_registered",
                event_at="2026-10-08T00:10:05+00:00",
                symbols=["NVDA"],
            ),
            alpaca_event(
                "stream_worker_error",
                event_at="2026-10-08T00:10:06+00:00",
                worker_status="FAILED",
                stream_error_type="RuntimeError",
                symbols=["NVDA"],
            ),
        ],
        repo_sha=ALPACA_SHA,
        now=T0 + timedelta(seconds=1),
    )

    assert cycle.provider_ids == ("alpaca",)
    assert cycle.snapshots[0].record.health_state is ProviderHealthState.DEGRADED
    assert cycle.transition_count == 1
    assert cycle.shadow_results[0].notification_plans[0].severity == "warning"
    assert cycle.snapshots[0].record.capabilities["entitlement_status"] == "UNKNOWN"


def test_negative_probe_flows_to_specific_shadow_alert_without_generic_duplicate():
    cycle = ProviderShadowRuntimePipeline().process_negative_provider_probe(
        negative_probe(),
        now=T0,
    )

    assert cycle.provider_ids == ("openai",)
    assert cycle.snapshots[0].record.health_state is ProviderHealthState.EXHAUSTED
    assert [
        item.code for item in cycle.shadow_results[0].evaluation.transitions
    ] == ["BILLING_STATUS_EXHAUSTED"]
    assert cycle.planned_notification_count == 1
    assert cycle.actual_notification_count == 0


def test_time_reversal_is_rejected_before_observer_or_shadow_state_is_mutated():
    pipeline = ProviderShadowRuntimePipeline()
    payload = negative_probe()

    with pytest.raises(
        ValueError,
        match="now must not be before provider evidence observed_at",
    ):
        pipeline.process_negative_provider_probe(
            payload,
            now=T0 - timedelta(seconds=1),
        )

    cycle = pipeline.process_negative_provider_probe(
        payload,
        now=T0,
    )
    assert cycle.transition_count == 1
    assert cycle.planned_notification_count == 1


def test_older_runtime_evidence_cannot_create_spurious_recovery():
    pipeline = ProviderShadowRuntimePipeline()
    latest = heartbeat(
        sequence=8,
        emitted_at_utc="2026-10-08T00:10:10+00:00",
        last_push_utc="2026-10-08T00:10:09+00:00",
        controller_lifecycle="FAILED",
        controller_findings_tail=["transport-down"],
    )
    older = heartbeat(
        sequence=7,
        emitted_at_utc="2026-10-08T00:10:05+00:00",
        last_push_utc="2026-10-08T00:10:04+00:00",
        controller_lifecycle="CONNECTED",
        controller_findings_tail=[],
    )

    opened = pipeline.process_opend_heartbeat(
        latest,
        now=T0 + timedelta(seconds=5),
    )
    ignored = pipeline.process_opend_heartbeat(
        older,
        now=T0 + timedelta(seconds=6),
    )

    assert opened.transition_count == 1
    assert ignored.snapshots[0].record.health_state is ProviderHealthState.FAILED
    assert ignored.transition_count == 0
    assert ignored.planned_notification_count == 0


def test_cycle_governance_is_explicit_and_not_an_admission_pass():
    cycle = ProviderShadowRuntimePipeline().process_negative_provider_probe(
        negative_probe(),
        now=T0,
    )

    assert cycle.validation_status == "VALIDATED"
    assert cycle.research_only is True
    assert cycle.data_admission == "NOT_EVALUATED"
    assert cycle.radar_admission == "BLOCKED"
    assert cycle.live_trade is False
    assert cycle.actual_notification_count == 0


def test_naive_now_is_rejected_without_runtime_state_write():
    pipeline = ProviderShadowRuntimePipeline()
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        pipeline.process_negative_provider_probe(
            negative_probe(),
            now=datetime(2026, 10, 8, 0, 10, 5),
        )

    cycle = pipeline.process_negative_provider_probe(
        negative_probe(),
        now=T0,
    )
    assert cycle.transition_count == 1
