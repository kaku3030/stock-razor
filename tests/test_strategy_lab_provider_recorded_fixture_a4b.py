from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

import src.services.strategy_lab.provider_recorded_fixture as binding
from src.services.a_share_provider_lineage import RealtimeSourceLineage
from src.services.strategy_lab.provider_recorded_fixture import (
    A0_AUTHORITY_SOURCE_REF,
    A1_AUTHORITY_SOURCE_REF,
    NORMALIZER_SHA256,
    NORMALIZER_VERSION,
    PROVIDER_RECORDED_FIXTURE_SCHEMA_VERSION,
    CapturedProviderAuthorityReceipt,
    VerifiedCapturedProviderAuthority,
    authority_receipt_bytes_sha256,
    build_pre_seal_a_share_provider_authority_receipt,
    capture_current_a_share_provider_authority,
    convert_sealed_capture_to_provider_fixture,
    diagnose_current_provider_authority,
    load_captured_provider_authority_receipt,
)
from src.services.strategy_lab.raw_capture import (
    NORMALIZATION_LINEAGE_VERSION,
    RAW_CAPTURE_MANIFEST_VERSION,
    RAW_CAPTURE_MANIFEST_VERSION_V2,
    encode_raw_capture,
    load_sealed_raw_capture,
)
from src.services.strategy_lab.recorded_fixture import REPRESENTATION_NORMALIZED_LICENSED_CSV
from src.services.strategy_lab.replay_contract import InMemoryEventStore, stable_hash

UTC = timezone.utc
TOOL_COMMIT = "05b872b2da9eb077070b4aa3ef1261671f3825ce"
TOOL_BLOB = "890e3bdca155e6eb65095d9ba7160aeba78a0f48"


def artifact_payload(*, status="OK", response="2026-09-10T10:00:01Z", rows=None, diagnostics=None):
    if rows is None:
        rows = [
            {
                "datetime": "2026-09-09T01:45:00+00:00",
                "open": "10.00",
                "high": "10.20",
                "low": "9.90",
                "close": "10.10",
                "volume": "12345",
            },
            {
                "datetime": "2026-09-09T02:00:00+00:00",
                "open": "10.10",
                "high": "10.30",
                "low": "10.00",
                "close": "10.25",
                "volume": "23456",
            },
        ]
    return {
        "schema_version": "raw-provider-capture-v0.1",
        "capture_id": "capture-akshare-em-aware-001",
        "provider_label": "AKSHARE_EASTMONEY_EVIDENCE_ONLY",
        "capture_tool_repository": "kaku3030/stock-razor",
        "capture_tool_path": "tools/provider_semantics/a_share/canonical_aware_fixture_probe.py",
        "capture_tool_commit_sha": TOOL_COMMIT,
        "capture_tool_blob_sha": TOOL_BLOB,
        "sdk_version": "research-fixture",
        "opend_version": "not-applicable",
        "artifact_created_at_utc": "2026-09-10T10:00:04Z",
        "observations": [
            {
                "observation_id": "history-cn-15m-1",
                "status": status,
                "operation": "history",
                "symbol": "000001.SZ",
                "ktype": "K_15M",
                "session": "REGULAR",
                "autype": "NONE",
                "request_params": {"trade_date": "2026-09-09"},
                "request_started_at_utc": "2026-09-10T10:00:00Z",
                "response_received_at_utc": response,
                "parent_observed_at_utc": "2026-09-10T10:00:02Z",
                "raw_payload": {"raw_rows": rows},
                "serialization_diagnostics": diagnostics or [],
            }
        ],
    }


def write_sealed(tmp_path, payload=None):
    payload = payload or artifact_payload()
    artifact_bytes = encode_raw_capture(payload)
    artifact_path = tmp_path / "capture.json"
    artifact_path.write_bytes(artifact_bytes)
    manifest = {
        "schema_version": RAW_CAPTURE_MANIFEST_VERSION,
        "capture_id": payload["capture_id"],
        "artifact_filename": artifact_path.name,
        "artifact_sha256": sha256(artifact_bytes).hexdigest(),
        "sealed_at_utc": "2026-09-10T10:00:05Z",
    }
    manifest_path = tmp_path / "capture.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_sealed_raw_capture(artifact_path, manifest_path)


def capture_receipt(sealed):
    return capture_current_a_share_provider_authority(
        sealed,
        observation_id="history-cn-15m-1",
        source_token="akshare_em",
        endpoint_id="akshare.eastmoney_intraday",
        market="cn",
    )


def capture_authority(sealed):
    receipt = capture_receipt(sealed)
    return load_captured_provider_authority_receipt(receipt.to_json_bytes())


def pre_seal_receipt(payload, artifact_bytes, *, observation_id="history-cn-15m-1"):
    return build_pre_seal_a_share_provider_authority_receipt(
        artifact_bytes,
        observation_id=observation_id,
        source_token="akshare_em",
        endpoint_id="akshare.eastmoney_intraday",
        market="cn",
    )


def write_sealed_v2(tmp_path, payload=None, *, observation_id="history-cn-15m-1"):
    """Seal a v0.2 manifest whose anchor binds a receipt minted before sealing.

    Unlike ``write_sealed`` (legacy v0.1, no anchor), the receipt here is
    built directly from raw artifact bytes -- before any manifest exists --
    so the manifest's ``authority_receipt_sha256`` can only ever describe a
    receipt that already existed at sealing time.
    """

    payload = payload or artifact_payload()
    artifact_bytes = encode_raw_capture(payload)
    receipt = pre_seal_receipt(payload, artifact_bytes, observation_id=observation_id)
    artifact_path = tmp_path / "capture.json"
    artifact_path.write_bytes(artifact_bytes)
    manifest = {
        "schema_version": RAW_CAPTURE_MANIFEST_VERSION_V2,
        "capture_id": payload["capture_id"],
        "artifact_filename": artifact_path.name,
        "artifact_sha256": sha256(artifact_bytes).hexdigest(),
        "sealed_at_utc": "2026-09-10T10:00:05Z",
        "authority_receipt_sha256": authority_receipt_bytes_sha256(receipt),
    }
    manifest_path = tmp_path / "capture.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    authority = load_captured_provider_authority_receipt(receipt.to_json_bytes())
    return sealed, authority


def make_fixture(tmp_path):
    sealed, authority = write_sealed_v2(tmp_path)
    fixture = convert_sealed_capture_to_provider_fixture(
        sealed,
        observation_id="history-cn-15m-1",
        authority=authority,
        fixture_id="provider-fixture-cn-001",
    )
    return sealed, authority, fixture


def test_a4b_keeps_a3_static_representation_unchanged_and_uses_separate_variant(tmp_path):
    _, _, fixture = make_fixture(tmp_path)
    assert REPRESENTATION_NORMALIZED_LICENSED_CSV == "NORMALIZED_FROM_LICENSED_PUBLIC_CSV"
    assert fixture.schema_version == PROVIDER_RECORDED_FIXTURE_SCHEMA_VERSION
    assert not hasattr(fixture, "representation")


def test_valid_verified_capture_converts_with_one_to_one_lineage(tmp_path):
    sealed, authority, fixture = make_fixture(tmp_path)
    assert len(fixture.rows) == len(fixture.row_lineages) == 2
    assert fixture.available_at == datetime(2026, 9, 10, 10, 0, 1, tzinfo=UTC)
    assert fixture.observed_at == datetime(2026, 9, 10, 10, 0, 2, tzinfo=UTC)
    assert fixture.authority.digest == authority.digest
    assert fixture.raw_artifact_sha256 == sealed.manifest.artifact_sha256
    assert fixture.normalizer_version == NORMALIZER_VERSION
    assert fixture.normalizer_sha256 == NORMALIZER_SHA256
    assert fixture.rows[0]["datetime"] == "2026-09-09T01:45:00.000000Z"
    assert fixture.row_lineages[1]["raw_path"].endswith("raw_rows[1]")
    assert all(item["schema_version"] == NORMALIZATION_LINEAGE_VERSION for item in fixture.row_lineages)


def test_verified_authority_cannot_be_constructed_directly():
    with pytest.raises(TypeError, match="persisted capture receipt"):
        VerifiedCapturedProviderAuthority()


def test_uninitialized_verified_authority_object_is_rejected_before_use(tmp_path):
    sealed = write_sealed(tmp_path)
    fake = object.__new__(VerifiedCapturedProviderAuthority)
    with pytest.raises(ValueError, match="not verified"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=fake,
            fixture_id="uninitialized-authority",
        )


def test_unverified_or_wrong_type_cannot_convert(tmp_path):
    _, authority, _ = make_fixture(tmp_path)
    with pytest.raises(ValueError, match="verified SealedRawCapture"):
        convert_sealed_capture_to_provider_fixture(
            object(),
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="bad",
        )


def test_capture_time_authority_is_digest_bound_to_raw_artifact(tmp_path):
    sealed, authority, _ = make_fixture(tmp_path)
    assert authority.raw_artifact_sha256 == sealed.manifest.artifact_sha256
    assert authority.captured_at == datetime(2026, 9, 10, 10, 0, 2, tzinfo=UTC)
    assert authority.a0_authority_source_ref == A0_AUTHORITY_SOURCE_REF
    assert authority.a1_authority_source_ref == A1_AUTHORITY_SOURCE_REF
    canonical = authority.canonical_payload()
    assert canonical["digest"] == stable_hash({k: v for k, v in canonical.items() if k != "digest"})


def test_persisted_authority_receipt_tamper_is_revalidated_before_conversion(tmp_path):
    sealed, authority, _ = make_fixture(tmp_path)
    payload = json.loads(authority.persisted_receipt_bytes())
    payload["source_token"] = "forged"
    object.__setattr__(authority, "_receipt_bytes", json.dumps(payload).encode("utf-8"))
    with pytest.raises(ValueError):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="tampered-authority",
        )


def test_wrong_source_endpoint_cannot_be_captured_as_a1_authority(tmp_path):
    sealed = write_sealed(tmp_path)
    with pytest.raises(ValueError, match="not admitted by accepted A1"):
        capture_current_a_share_provider_authority(
            sealed,
            observation_id="history-cn-15m-1",
            source_token="akshare_em",
            endpoint_id="akshare.eastmoney_spot",
        )


def test_unknown_source_cannot_be_captured_as_a0_authority(tmp_path):
    sealed = write_sealed(tmp_path)
    with pytest.raises(ValueError, match="not admitted by accepted A0"):
        capture_current_a_share_provider_authority(
            sealed,
            observation_id="history-cn-15m-1",
            source_token="unknown",
            endpoint_id="unknown.endpoint",
        )


def test_capture_factory_fails_loud_if_live_a0_no_longer_matches_pinned_source(monkeypatch, tmp_path):
    sealed = write_sealed(tmp_path)
    monkeypatch.setattr(binding, "CN_REALTIME_SOURCE_LINEAGE", {})
    with pytest.raises(RuntimeError, match="A0 provider authority changed"):
        capture_authority(sealed)


def test_current_authority_drift_is_diagnostic_only(monkeypatch, tmp_path):
    _, authority, fixture = make_fixture(tmp_path)
    original_digest = fixture.fixture_digest
    drifted = RealtimeSourceLineage(
        source_token="akshare_em",
        adapter_id="future-adapter",
        upstream_lineage_id="future-upstream",
        endpoint_id="future.endpoint",
        markets=("cn",),
    )
    monkeypatch.setattr(binding, "CN_REALTIME_SOURCE_LINEAGE", {"akshare_em": drifted})
    diagnostic = diagnose_current_provider_authority(authority)
    assert diagnostic.status == "CURRENT_AUTHORITY_DRIFT"
    assert "adapter_id" in diagnostic.differences
    assert fixture.fixture_digest == original_digest


def test_authority_bound_to_different_raw_artifact_fails_closed(tmp_path_factory):
    first = write_sealed(tmp_path_factory.mktemp("first"))
    payload = artifact_payload()
    payload["capture_id"] = "capture-akshare-em-aware-002"
    second = write_sealed(tmp_path_factory.mktemp("second"), payload)
    authority = capture_authority(first)
    with pytest.raises(ValueError, match="different raw artifact"):
        convert_sealed_capture_to_provider_fixture(
            second,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="cross-bound",
        )


def test_naive_row_datetime_is_never_localized_by_guesswork(tmp_path):
    payload = artifact_payload()
    payload["observations"][0]["raw_payload"]["raw_rows"][0]["datetime"] = "2026-09-09T09:45:00"
    sealed, authority = write_sealed_v2(tmp_path, payload)
    with pytest.raises(ValueError, match="must be timezone-aware"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="naive-row",
        )


def test_numeric_float_is_not_silently_coerced_to_decimal_text(tmp_path):
    payload = artifact_payload()
    payload["observations"][0]["raw_payload"]["raw_rows"][0]["open"] = 10.0
    sealed, authority = write_sealed_v2(tmp_path, payload)
    with pytest.raises(ValueError, match="non-empty trimmed string"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="numeric-coercion",
        )


def test_empty_raw_rows_cannot_become_provider_recorded_fixture(tmp_path):
    sealed, authority = write_sealed_v2(tmp_path, artifact_payload(rows=[]))
    with pytest.raises(ValueError, match="non-empty raw_rows"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="empty",
        )


def test_timeout_or_non_pit_observation_cannot_convert(tmp_path_factory):
    authority = capture_authority(write_sealed(tmp_path_factory.mktemp("authority")))
    sealed = write_sealed(
        tmp_path_factory.mktemp("timeout"),
        artifact_payload(status="TIMEOUT", response=None),
    )
    with pytest.raises(ValueError, match="not eligible for point-in-time"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="timeout",
        )


def test_serialization_diagnostic_blocks_conversion(tmp_path_factory):
    authority = capture_authority(write_sealed(tmp_path_factory.mktemp("authority")))
    sealed = write_sealed(
        tmp_path_factory.mktemp("diagnostic"),
        artifact_payload(diagnostics=["upstream coercion observed"]),
    )
    with pytest.raises(ValueError, match="not eligible for point-in-time"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="diag",
        )


def test_event_time_after_verified_available_at_fails_closed(tmp_path):
    payload = artifact_payload()
    payload["observations"][0]["raw_payload"]["raw_rows"][1]["datetime"] = "2026-09-10T10:00:01.500000Z"
    sealed, authority = write_sealed_v2(tmp_path, payload)
    with pytest.raises(ValueError, match="after verified available_at"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="future-row",
        )


def test_lineage_count_mismatch_fails_closed(tmp_path):
    _, _, fixture = make_fixture(tmp_path)
    with pytest.raises(ValueError, match="one-to-one normalization lineage"):
        replace(fixture, row_lineages=fixture.row_lineages[:-1])


def test_stale_tampered_lineage_digest_fails_closed(tmp_path):
    _, _, fixture = make_fixture(tmp_path)
    first = dict(fixture.row_lineages[0])
    first["lineage_digest"] = "0" * 64
    tampered = (first, *fixture.row_lineages[1:])
    with pytest.raises(ValueError, match="normalization lineage digest mismatch"):
        replace(fixture, row_lineages=tampered)


def test_unknown_lineage_schema_cannot_be_rehashed_into_acceptance(tmp_path):
    _, _, fixture = make_fixture(tmp_path)
    first = dict(fixture.row_lineages[0])
    first["schema_version"] = "raw-normalization-lineage-v999"
    first["lineage_digest"] = stable_hash({k: v for k, v in first.items() if k != "lineage_digest"})
    tampered = (first, *fixture.row_lineages[1:])
    with pytest.raises(ValueError, match="lineage version mismatch"):
        replace(fixture, row_lineages=tampered)


def test_reordered_lineage_fails_closed(tmp_path):
    _, _, fixture = make_fixture(tmp_path)
    with pytest.raises(ValueError, match="row order/path mismatch"):
        replace(fixture, row_lineages=tuple(reversed(fixture.row_lineages)))


def test_identical_conversion_is_100_of_100_deterministic(tmp_path):
    sealed, authority = write_sealed_v2(tmp_path)
    digests = {
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="deterministic",
        ).fixture_digest
        for _ in range(100)
    }
    assert len(digests) == 1


def test_raw_artifact_tamper_after_load_is_reverified_before_conversion(tmp_path):
    sealed = write_sealed(tmp_path)
    authority = capture_authority(sealed)
    object.__setattr__(sealed, "_artifact_bytes", sealed._artifact_bytes + b"\n")
    with pytest.raises(ValueError, match="digest verification failed"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="tamper",
        )


def test_materialized_events_retain_raw_authority_lineage_and_entry_gate_closed(tmp_path):
    _, authority, fixture = make_fixture(tmp_path)
    events = fixture.materialize_events()
    assert len(events) == 2
    assert all(event.source_kind == "PROVIDER" for event in events)
    assert all(event.source_token == "akshare_em" for event in events)
    assert all(event.endpoint_id == "akshare.eastmoney_intraday" for event in events)
    assert all(event.payload["provider_authority_digest"] == authority.digest for event in events)
    assert all(event.payload["raw_artifact_sha256"] == fixture.raw_artifact_sha256 for event in events)
    assert all(event.payload["entry_gate"] == "CLOSED" for event in events)


def test_historical_resolver_admits_events_without_consulting_current_manifest(monkeypatch, tmp_path):
    _, _, fixture = make_fixture(tmp_path)
    monkeypatch.setattr(binding, "CN_REALTIME_SOURCE_LINEAGE", {})
    monkeypatch.setattr(binding, "CN_INTRADAY_ENDPOINT_EXTENSIONS", {})
    store = InMemoryEventStore(source_authority_resolver=fixture.historical_authority_resolver())
    for event in fixture.materialize_events():
        assert store.append(event) == "ACCEPTED"
    assert all("captured-provider-authority:sha256:" in event.source_authority_ref for event in store.events)


def test_conversion_has_no_current_registry_or_provider_side_effect_dependency(monkeypatch, tmp_path):
    sealed, authority, _ = make_fixture(tmp_path)

    class ExplodingRegistry:
        def get(self, *args, **kwargs):
            raise AssertionError("conversion must not consult current registry")

    monkeypatch.setattr(binding, "CN_REALTIME_SOURCE_LINEAGE", ExplodingRegistry())
    monkeypatch.setattr(binding, "CN_INTRADAY_ENDPOINT_EXTENSIONS", ExplodingRegistry())
    fixture = convert_sealed_capture_to_provider_fixture(
        sealed,
        observation_id="history-cn-15m-1",
        authority=authority,
        fixture_id="side-effect-free",
    )
    assert len(fixture.rows) == 2


def _receipt_json_for(sealed):
    return json.loads(capture_receipt(sealed).to_json_bytes())


def _rehash_receipt(payload):
    body = {key: value for key, value in payload.items() if key != "digest"}
    payload["digest"] = stable_hash(body)
    return payload


def _load_receipt_payload(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return load_captured_provider_authority_receipt(raw)


def test_capture_receipt_must_be_persisted_and_reloaded_before_conversion(tmp_path):
    sealed = write_sealed(tmp_path)
    receipt = capture_receipt(sealed)
    assert isinstance(receipt, CapturedProviderAuthorityReceipt)
    with pytest.raises(ValueError, match="verified captured provider authority"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=receipt,
            fixture_id="receipt-not-reloaded",
        )


def test_private_receipt_loader_cannot_mint_arbitrary_source_authority(tmp_path):
    sealed = write_sealed(tmp_path)
    payload = _receipt_json_for(sealed)
    payload["source_token"] = "forged_source"
    _rehash_receipt(payload)
    with pytest.raises(ValueError, match="not admitted by pinned A0 snapshot"):
        VerifiedCapturedProviderAuthority._from_persisted_receipt(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )


def test_self_digest_consistent_receipt_with_forged_adapter_is_rejected(tmp_path):
    sealed = write_sealed(tmp_path)
    payload = _receipt_json_for(sealed)
    payload["adapter_id"] = "forged-adapter"
    _rehash_receipt(payload)
    with pytest.raises(ValueError, match="adapter does not match"):
        _load_receipt_payload(payload)


def test_receipt_digest_tamper_is_rejected(tmp_path):
    payload = _receipt_json_for(write_sealed(tmp_path))
    payload["digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        _load_receipt_payload(payload)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("endpoint_id", "forged.endpoint", "endpoint is not admitted"),
        ("market", "hk", "first slice supports A-share"),
        ("upstream_lineage_id", "forged-upstream", "upstream lineage does not match"),
        ("a0_authority_source_ref", "forged-a0", "does not pin accepted A0"),
        ("a1_authority_source_ref", "forged-a1", "does not pin accepted A1"),
    ],
)
def test_receipt_authority_field_mutations_fail_closed(tmp_path, field, value, match):
    payload = _receipt_json_for(write_sealed(tmp_path))
    payload[field] = value
    _rehash_receipt(payload)
    with pytest.raises(ValueError, match=match):
        _load_receipt_payload(payload)


def test_pinned_a0_snapshot_mutation_cannot_be_rehashed_into_acceptance(tmp_path):
    payload = _receipt_json_for(write_sealed(tmp_path))
    payload["a0_registry_snapshot"]["akshare_em"]["adapter_id"] = "forged-adapter"
    _rehash_receipt(payload)
    with pytest.raises(ValueError, match="A0 snapshot digest mismatch"):
        _load_receipt_payload(payload)


def test_pinned_a1_snapshot_mutation_cannot_be_rehashed_into_acceptance(tmp_path):
    payload = _receipt_json_for(write_sealed(tmp_path))
    payload["a1_extension_snapshot"]["akshare_em"] = ["forged.endpoint"]
    _rehash_receipt(payload)
    with pytest.raises(ValueError, match="A1 snapshot digest mismatch"):
        _load_receipt_payload(payload)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("capture_id", "other-capture", "different capture/observation"),
        ("observation_id", "other-observation", "different capture/observation"),
        ("captured_at", "2026-09-10T10:00:03.000000Z", "time does not match"),
        ("raw_artifact_sha256", "1" * 64, "different raw artifact"),
    ],
)
def test_rehashed_receipt_binding_mutations_rejected_at_conversion(tmp_path, field, value, match):
    sealed = write_sealed(tmp_path)
    payload = _receipt_json_for(sealed)
    payload[field] = value
    authority = _load_receipt_payload(_rehash_receipt(payload))
    with pytest.raises(ValueError, match=match):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="binding-mutation",
        )


def test_legitimate_receipt_round_trip_is_byte_deterministic_and_resolver_stable(tmp_path):
    payload = artifact_payload()
    artifact_bytes = encode_raw_capture(payload)
    receipt = pre_seal_receipt(payload, artifact_bytes)
    raw = receipt.to_json_bytes()
    first = load_captured_provider_authority_receipt(raw)
    second = load_captured_provider_authority_receipt(first.persisted_receipt_bytes())
    assert first.persisted_receipt_bytes() == second.persisted_receipt_bytes() == raw
    assert first.digest == second.digest
    resolver = second.historical_resolver()
    resolved = resolver("akshare_em", "akshare.eastmoney_intraday", "cn")
    assert resolved is not None
    assert resolved.authority_ref == f"captured-provider-authority:sha256:{second.digest}"

    artifact_path = tmp_path / "capture.json"
    artifact_path.write_bytes(artifact_bytes)
    manifest = {
        "schema_version": RAW_CAPTURE_MANIFEST_VERSION_V2,
        "capture_id": payload["capture_id"],
        "artifact_filename": artifact_path.name,
        "artifact_sha256": sha256(artifact_bytes).hexdigest(),
        "sealed_at_utc": "2026-09-10T10:00:05Z",
        "authority_receipt_sha256": authority_receipt_bytes_sha256(receipt),
    }
    manifest_path = tmp_path / "capture.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)

    fixture = convert_sealed_capture_to_provider_fixture(
        sealed,
        observation_id="history-cn-15m-1",
        authority=second,
        fixture_id="round-trip",
    )
    first_ids = tuple(event.event_id for event in fixture.materialize_events())
    second_ids = tuple(event.event_id for event in fixture.materialize_events())
    assert first_ids == second_ids


# --- H-A4B-02: contemporaneous receipt origin -------------------------------
#
# A receipt being internally valid is not enough: A4b conversion must also
# prove the receipt was bound into the raw capture's manifest at the
# original sealing event, not minted against it afterward.


def test_h_a4b_02_a_legacy_retrospective_mint_is_rejected(tmp_path):
    """A. A v0.1 capture with no anchor stays ineligible even with a fresh, valid receipt."""

    sealed = write_sealed(tmp_path)
    authority = capture_authority(sealed)
    with pytest.raises(ValueError, match="no contemporaneous authority receipt anchor"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="legacy-retrospective-mint",
        )


def test_h_a4b_02_b_manifest_anchor_digest_mismatch_is_rejected(tmp_path):
    """B. A v0.2 manifest anchor that does not hash-match the persisted receipt bytes fails closed."""

    payload = artifact_payload()
    artifact_bytes = encode_raw_capture(payload)
    receipt = pre_seal_receipt(payload, artifact_bytes)
    artifact_path = tmp_path / "capture.json"
    artifact_path.write_bytes(artifact_bytes)
    manifest = {
        "schema_version": RAW_CAPTURE_MANIFEST_VERSION_V2,
        "capture_id": payload["capture_id"],
        "artifact_filename": artifact_path.name,
        "artifact_sha256": sha256(artifact_bytes).hexdigest(),
        "sealed_at_utc": "2026-09-10T10:00:05Z",
        "authority_receipt_sha256": "0" * 64,
    }
    manifest_path = tmp_path / "capture.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    authority = load_captured_provider_authority_receipt(receipt.to_json_bytes())
    with pytest.raises(ValueError, match="anchor mismatch"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="anchor-digest-mismatch",
        )


def test_h_a4b_02_c_cross_artifact_receipt_reuse_is_rejected(tmp_path_factory):
    """C. A validly capture-time-anchored receipt from artifact A cannot authorize artifact B."""

    sealed_a, authority_a = write_sealed_v2(tmp_path_factory.mktemp("artifact-a"))
    payload_b = artifact_payload()
    payload_b["capture_id"] = "capture-akshare-em-aware-crossb"
    sealed_b, _ = write_sealed_v2(tmp_path_factory.mktemp("artifact-b"), payload_b)
    with pytest.raises(ValueError, match="different raw artifact"):
        convert_sealed_capture_to_provider_fixture(
            sealed_b,
            observation_id="history-cn-15m-1",
            authority=authority_a,
            fixture_id="cross-artifact-reuse",
        )


def test_h_a4b_02_d_anchor_tamper_after_seal_is_rejected(tmp_path):
    """D. Mutating the sealed manifest's immutable anchor is detected and rejected."""

    sealed, authority = write_sealed_v2(tmp_path)
    tampered_manifest = replace(sealed.manifest, authority_receipt_sha256="1" * 64)
    object.__setattr__(sealed, "_manifest", tampered_manifest)
    with pytest.raises(ValueError, match="anchor mismatch"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="anchor-tamper",
        )


def test_h_a4b_02_e_valid_v02_capture_time_anchored_receipt_is_accepted(tmp_path):
    """E. The legitimate capture-time-anchored path seals, loads, reloads, and converts cleanly."""

    sealed, authority = write_sealed_v2(tmp_path)
    assert sealed.manifest.schema_version == RAW_CAPTURE_MANIFEST_VERSION_V2
    assert sealed.manifest.is_authority_receipt_anchored
    reloaded_authority = load_captured_provider_authority_receipt(authority.persisted_receipt_bytes())
    fixture = convert_sealed_capture_to_provider_fixture(
        sealed,
        observation_id="history-cn-15m-1",
        authority=reloaded_authority,
        fixture_id="v02-positive-path",
    )
    first_ids = tuple(event.event_id for event in fixture.materialize_events())
    second_ids = tuple(event.event_id for event in fixture.materialize_events())
    assert first_ids == second_ids
    assert len(fixture.rows) == 2


def test_h_a4b_02_f_legacy_v01_capture_still_loads_for_ordinary_a4_use(tmp_path):
    """F. Legacy v0.1 loading/PIT semantics are unaffected by the stricter A4b gate."""

    sealed = write_sealed(tmp_path)
    assert sealed.manifest.schema_version == RAW_CAPTURE_MANIFEST_VERSION
    assert not sealed.manifest.is_authority_receipt_anchored
    available_at, observed_at = sealed.pit_binding("history-cn-15m-1")
    assert available_at is not None
    assert observed_at is not None
    assert sealed.artifact.capture_id == "capture-akshare-em-aware-001"


def test_h_a4b_02_g_private_mint_helper_cannot_bypass_a_missing_anchor(tmp_path):
    """G. Even the private mint helper cannot conjure an anchor a v0.1 manifest never sealed."""

    sealed = write_sealed(tmp_path)
    receipt = binding._mint_captured_provider_authority_receipt(
        raw_artifact_sha256=sealed.manifest.artifact_sha256,
        capture_id=sealed.artifact.capture_id,
        observation_id="history-cn-15m-1",
        captured_at=sealed.pit_binding("history-cn-15m-1")[1],
        source_token="akshare_em",
        endpoint_id="akshare.eastmoney_intraday",
        market="cn",
    )
    authority = load_captured_provider_authority_receipt(receipt.to_json_bytes())
    with pytest.raises(ValueError, match="no contemporaneous authority receipt anchor"):
        convert_sealed_capture_to_provider_fixture(
            sealed,
            observation_id="history-cn-15m-1",
            authority=authority,
            fixture_id="private-helper-bypass",
        )


def test_h_a4b_02_h_registry_drift_does_not_rewrite_accepted_v02_evidence(monkeypatch, tmp_path):
    """H. Current A0/A1 registry drift stays diagnostic-only for v0.2-anchored evidence too."""

    sealed, authority = write_sealed_v2(tmp_path)
    fixture = convert_sealed_capture_to_provider_fixture(
        sealed,
        observation_id="history-cn-15m-1",
        authority=authority,
        fixture_id="v02-registry-drift",
    )
    original_digest = fixture.fixture_digest
    drifted = RealtimeSourceLineage(
        source_token="akshare_em",
        adapter_id="future-adapter",
        upstream_lineage_id="future-upstream",
        endpoint_id="future.endpoint",
        markets=("cn",),
    )
    monkeypatch.setattr(binding, "CN_REALTIME_SOURCE_LINEAGE", {"akshare_em": drifted})
    diagnostic = diagnose_current_provider_authority(authority)
    assert diagnostic.status == "CURRENT_AUTHORITY_DRIFT"
    assert fixture.fixture_digest == original_digest
    refixture = convert_sealed_capture_to_provider_fixture(
        sealed,
        observation_id="history-cn-15m-1",
        authority=authority,
        fixture_id="v02-registry-drift",
    )
    assert refixture.fixture_digest == original_digest
