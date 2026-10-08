from datetime import datetime, timezone

import pytest

from src.services.provider_lifecycle import (
    ProviderHealthState,
    ProviderRuntimeIngestError,
    ProviderRuntimeObserver,
    build_cn_provider_observations_from_cloud_snapshot,
    ingest_cn_cloud_observation,
)


SHA = "bd5d094f21c3421c41b65feba474c7ec46ecf2c1"


def frame(
    *,
    provider_used,
    provider_lineage,
    fallback_from,
    fallback_reason=None,
    status="PASS",
    error=None,
    currentness="UNPROVEN",
):
    return {
        "status": status,
        "provider_used": provider_used,
        "provider_lineage": provider_lineage,
        "fallback_from": fallback_from,
        "fallback_reason": fallback_reason,
        "error": error,
        "request_latency_ms": 12.5,
        "currentness": currentness,
    }


def snapshot(*, symbols, providers_used, **overrides):
    payload = {
        "schema": "stock_razor_cn_eastmoney_observation_v1",
        "repo_sha": SHA,
        "runtime_instance_id": "cn-runtime-1",
        "sequence": 9,
        "emitted_at_utc": "2026-10-08T00:10:05+00:00",
        "host_id": "aws-cn-1",
        "status": "PASS",
        "symbols": symbols,
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "providers_used": providers_used,
        "provider_lineages": ["eastmoney", "tencent"],
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    payload.update(overrides)
    return payload


def one_symbol(timeframes):
    return {
        "159611": {
            "status": "PASS",
            "providers_used": [],
            "timeframes": timeframes,
        }
    }


def by_provider(observations):
    return {item.provider_id: item for item in observations}


def test_eastmoney_direct_success_is_evidence_but_not_healthy():
    observations = build_cn_provider_observations_from_cloud_snapshot(
        snapshot(
            providers_used=["eastmoney"],
            symbols=one_symbol({
                "1d": frame(
                    provider_used="eastmoney",
                    provider_lineage="eastmoney",
                    fallback_from=None,
                ),
                "60m": frame(
                    provider_used="eastmoney",
                    provider_lineage="eastmoney",
                    fallback_from=None,
                ),
                "15m": frame(
                    provider_used="eastmoney",
                    provider_lineage="eastmoney",
                    fallback_from=None,
                ),
            }),
        )
    )
    assert len(observations) == 1
    item = observations[0]
    assert item.provider_id == "eastmoney"
    assert item.fields["health_state"].value is ProviderHealthState.UNKNOWN
    assert item.fields["failure_reason"].value is None
    assert "last_failure" not in item.fields
    assert "latency_ms" not in item.fields
    assert "freshness_ms" not in item.fields
    caps = item.fields["capabilities"].value
    assert caps["direct_success_frame_count"] == 3
    assert caps["fallback_trigger_frame_count"] == 0


def test_tencent_fallback_degrades_only_eastmoney_not_tencent():
    observations = by_provider(
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["tencent"],
                symbols=one_symbol({
                    "1d": frame(
                        provider_used="tencent",
                        provider_lineage="tencent",
                        fallback_from="eastmoney",
                        fallback_reason="RuntimeError",
                    ),
                    "60m": frame(
                        provider_used="tencent",
                        provider_lineage="tencent",
                        fallback_from="eastmoney",
                        fallback_reason="RuntimeError",
                        currentness="PROVEN",
                    ),
                    "15m": frame(
                        provider_used="tencent",
                        provider_lineage="tencent",
                        fallback_from="eastmoney",
                        fallback_reason="RuntimeError",
                        currentness="PROVEN",
                    ),
                }),
                intraday_timestamp_semantics_proven=True,
                intraday_currentness_proven=True,
            )
        )
    )
    eastmoney = observations["eastmoney"]
    tencent = observations["tencent"]

    assert eastmoney.fields["health_state"].value is ProviderHealthState.DEGRADED
    assert "RuntimeError" in eastmoney.fields["failure_reason"].value
    assert eastmoney.fields["last_failure"].value == datetime(
        2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc
    )

    assert tencent.fields["health_state"].value is ProviderHealthState.UNKNOWN
    assert tencent.fields["failure_reason"].value is None
    assert "last_failure" not in tencent.fields
    assert "latency_ms" not in tencent.fields
    assert "freshness_ms" not in tencent.fields
    caps = tencent.fields["capabilities"].value
    assert caps["fallback_success_frame_count"] == 3
    assert caps["currentness_proven_frames"] == (
        "159611:15m",
        "159611:60m",
    )
    assert caps["intraday_currentness_proven"] is True
    assert caps["radar_admission"] == "BLOCKED"
    assert caps["live_trade"] is False


def test_both_source_failure_degrades_both_without_claiming_failed():
    blocked = frame(
        provider_used=None,
        provider_lineage=None,
        fallback_from="eastmoney",
        fallback_reason="RuntimeError|TENCENT:CloudObservationError",
        status="BLOCKED",
        error="RuntimeError|TENCENT:CloudObservationError",
    )
    observations = by_provider(
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=[],
                status="BLOCKED",
                symbols=one_symbol({
                    "1d": blocked,
                    "60m": blocked,
                    "15m": blocked,
                }),
            )
        )
    )
    assert observations["eastmoney"].fields["health_state"].value is ProviderHealthState.DEGRADED
    assert observations["tencent"].fields["health_state"].value is ProviderHealthState.DEGRADED
    assert "RuntimeError" in observations["eastmoney"].fields["failure_reason"].value
    assert "CloudObservationError" in observations["tencent"].fields["failure_reason"].value


def test_mixed_direct_and_fallback_keeps_provider_evidence_separate():
    observations = by_provider(
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["eastmoney", "tencent"],
                status="PASS",
                symbols=one_symbol({
                    "1d": frame(
                        provider_used="eastmoney",
                        provider_lineage="eastmoney",
                        fallback_from=None,
                    ),
                    "60m": frame(
                        provider_used="tencent",
                        provider_lineage="tencent",
                        fallback_from="eastmoney",
                        fallback_reason="TimeoutError",
                    ),
                    "15m": frame(
                        provider_used="eastmoney",
                        provider_lineage="eastmoney",
                        fallback_from=None,
                    ),
                }),
            )
        )
    )
    eastmoney = observations["eastmoney"]
    tencent = observations["tencent"]
    assert eastmoney.fields["health_state"].value is ProviderHealthState.DEGRADED
    assert eastmoney.fields["capabilities"].value["success_frame_count"] == 2
    assert eastmoney.fields["capabilities"].value["failure_frame_count"] == 1
    assert tencent.fields["health_state"].value is ProviderHealthState.UNKNOWN
    assert tencent.fields["capabilities"].value["success_frames"] == (
        "159611:60m",
    )


def test_provenance_is_exact_per_provider_and_field():
    observations = by_provider(
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["tencent"],
                symbols=one_symbol({
                    "15m": frame(
                        provider_used="tencent",
                        provider_lineage="tencent",
                        fallback_from="eastmoney",
                        fallback_reason="RuntimeError",
                    ),
                }),
            )
        )
    )
    evidence = observations["tencent"].fields["capabilities"].provenance
    assert evidence.source == "cn_eastmoney_cloud_observation"
    assert evidence.runtime_id == "cn-runtime-1"
    assert evidence.repo_sha == SHA
    assert evidence.observed_at == datetime(
        2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc
    )
    assert evidence.evidence_id == (
        "cn-cloud:cn-runtime-1:9:tencent:capabilities"
    )


def test_static_provider_lineages_do_not_create_runtime_provider_evidence():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="no provider-specific frame evidence",
    ):
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=[],
                symbols={},
                status="BLOCKED",
                error="CloudObservationError",
            )
        )


def test_declared_providers_used_must_match_frame_evidence():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="providers_used does not match",
    ):
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["eastmoney"],
                symbols=one_symbol({
                    "15m": frame(
                        provider_used="tencent",
                        provider_lineage="tencent",
                        fallback_from="eastmoney",
                        fallback_reason="RuntimeError",
                    ),
                }),
            )
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"radar_admission": "PASS"},
        {"live_trade": True},
        {"research_only": False},
        {"can_confirm_signal": True},
        {"repo_sha": "abc"},
        {"sequence": 0},
        {"provider_lineages": ["eastmoney"]},
        {"provider_policy": "OTHER"},
    ],
)
def test_cn_governance_and_identity_violations_are_rejected(overrides):
    with pytest.raises(ProviderRuntimeIngestError):
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["eastmoney"],
                symbols=one_symbol({
                    "1d": frame(
                        provider_used="eastmoney",
                        provider_lineage="eastmoney",
                        fallback_from=None,
                    ),
                }),
                **overrides,
            )
        )


def test_uppercase_repo_sha_is_rejected_not_normalized():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="lowercase git SHA",
    ):
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["eastmoney"],
                repo_sha=SHA.upper(),
                symbols=one_symbol({
                    "1d": frame(
                        provider_used="eastmoney",
                        provider_lineage="eastmoney",
                        fallback_from=None,
                    ),
                }),
            )
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "intraday_timestamp_semantics_proven",
        "intraday_currentness_proven",
    ],
)
def test_cn_top_level_evidence_flags_must_be_boolean(field_name):
    with pytest.raises(
        ProviderRuntimeIngestError,
        match=f"{field_name} must be a boolean",
    ):
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["eastmoney"],
                symbols=one_symbol({
                    "1d": frame(
                        provider_used="eastmoney",
                        provider_lineage="eastmoney",
                        fallback_from=None,
                    ),
                }),
                **{field_name: "true"},
            )
        )


def test_tencent_currentness_rejects_unknown_value():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="currentness must be PROVEN or UNPROVEN",
    ):
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["tencent"],
                symbols=one_symbol({
                    "15m": frame(
                        provider_used="tencent",
                        provider_lineage="tencent",
                        fallback_from="eastmoney",
                        fallback_reason="RuntimeError",
                        currentness="MAYBE",
                    ),
                }),
            )
        )


def test_provider_used_lineage_and_fallback_must_agree():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="tencent fallback lineage mismatch",
    ):
        build_cn_provider_observations_from_cloud_snapshot(
            snapshot(
                providers_used=["tencent"],
                symbols=one_symbol({
                    "15m": frame(
                        provider_used="tencent",
                        provider_lineage="tencent",
                        fallback_from=None,
                    ),
                }),
            )
        )


def test_end_to_end_ingest_uses_registry_roles_and_keeps_admission_separate():
    observer = ProviderRuntimeObserver()
    snapshots = ingest_cn_cloud_observation(
        observer,
        snapshot(
            providers_used=["tencent"],
            symbols=one_symbol({
                "15m": frame(
                    provider_used="tencent",
                    provider_lineage="tencent",
                    fallback_from="eastmoney",
                    fallback_reason="ConnectionResetError",
                    currentness="PROVEN",
                ),
            }),
            intraday_timestamp_semantics_proven=True,
            intraday_currentness_proven=True,
        ),
    )
    mapped = {item.record.provider_id: item for item in snapshots}
    assert mapped["eastmoney"].record.role.value == "PRIMARY"
    assert mapped["eastmoney"].record.fallback_provider == "tencent"
    assert mapped["tencent"].record.role.value == "FALLBACK"
    assert mapped["tencent"].record.freshness_ms is None
    assert mapped["tencent"].record.latency_ms is None
