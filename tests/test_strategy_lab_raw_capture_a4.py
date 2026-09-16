from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from src.services.strategy_lab.raw_capture import (
    RAW_CAPTURE_MANIFEST_VERSION,
    RAW_CAPTURE_MANIFEST_VERSION_V2,
    RawCaptureArtifact,
    RawCaptureManifest,
    RawCaptureObservation,
    build_row_normalization_lineage,
    encode_raw_capture,
    load_sealed_raw_capture,
    parse_and_digest_raw_capture_artifact,
)

UTC = timezone.utc
TOOL_COMMIT = "05b872b2da9eb077070b4aa3ef1261671f3825ce"
TOOL_BLOB = "890e3bdca155e6eb65095d9ba7160aeba78a0f48"
NORMALIZER_SHA = "1" * 64


def artifact_payload(*, status="OK", response="2026-09-10T10:00:01Z", diagnostics=None):
    return {
        "schema_version": "raw-provider-capture-v0.1",
        "capture_id": "capture-futu-history-001",
        "provider_label": "FUTU_EVIDENCE_ONLY",
        "capture_tool_repository": "kaku3030/stock-razor",
        "capture_tool_path": "tools/provider_semantics/futu/kline_snapshot_probe.py",
        "capture_tool_commit_sha": TOOL_COMMIT,
        "capture_tool_blob_sha": TOOL_BLOB,
        "sdk_version": "10.08.6808",
        "opend_version": "1010",
        "artifact_created_at_utc": "2026-09-10T10:00:04Z",
        "observations": [
            {
                "observation_id": "history-K_15M-1",
                "status": status,
                "operation": "history",
                "symbol": "US.QQQ",
                "ktype": "K_15M",
                "session": "RTH",
                "autype": "NONE",
                "request_params": {
                    "start": "2026-09-09",
                    "end": "2026-09-09",
                    "max_count": 1000,
                },
                "request_started_at_utc": "2026-09-10T10:00:00Z",
                "response_received_at_utc": response,
                "parent_observed_at_utc": "2026-09-10T10:00:02Z",
                "raw_payload": {
                    "raw_rows": [
                        {
                            "time_key": "2026-09-09 09:45:00",
                            "open": 100.0,
                            "high": 101.0,
                            "low": 99.0,
                            "close": 100.5,
                            "volume": 12345,
                        },
                        {
                            "time_key": "2026-09-09 10:00:00",
                            "open": 100.5,
                            "high": 102.0,
                            "low": 100.0,
                            "close": 101.5,
                            "volume": 23456,
                        },
                    ]
                },
                "serialization_diagnostics": diagnostics or [],
            }
        ],
    }


def write_sealed(tmp_path, payload=None, *, sealed_at="2026-09-10T10:00:05Z"):
    payload = payload or artifact_payload()
    artifact_bytes = encode_raw_capture(payload)
    artifact_path = tmp_path / "capture.json"
    artifact_path.write_bytes(artifact_bytes)
    manifest = {
        "schema_version": RAW_CAPTURE_MANIFEST_VERSION,
        "capture_id": payload["capture_id"],
        "artifact_filename": artifact_path.name,
        "artifact_sha256": sha256(artifact_bytes).hexdigest(),
        "sealed_at_utc": sealed_at,
    }
    manifest_path = tmp_path / "capture.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return artifact_path, manifest_path


def test_valid_synchronous_capture_has_distinct_pit_clocks(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    available_at, observed_at = sealed.pit_binding("history-K_15M-1")
    assert available_at == datetime(2026, 9, 10, 10, 0, 1, tzinfo=UTC)
    assert observed_at == datetime(2026, 9, 10, 10, 0, 2, tzinfo=UTC)
    assert available_at < observed_at


def test_success_cannot_substitute_request_start_for_missing_receive_time():
    payload = artifact_payload(response=None)
    with pytest.raises(ValueError, match="requires response_received_at"):
        RawCaptureArtifact.from_mapping(payload)


def test_timeout_is_preserved_but_not_pit_eligible(tmp_path):
    payload = artifact_payload(status="TIMEOUT", response=None)
    artifact_path, manifest_path = write_sealed(tmp_path, payload)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    with pytest.raises(ValueError, match="not eligible for point-in-time"):
        sealed.pit_binding("history-K_15M-1")


def test_response_before_request_fails_closed():
    payload = artifact_payload(response="2026-09-10T09:59:59Z")
    with pytest.raises(ValueError, match="cannot precede request_started_at"):
        RawCaptureArtifact.from_mapping(payload)


def test_parent_observation_before_response_fails_closed():
    payload = artifact_payload(response="2026-09-10T10:00:03Z")
    with pytest.raises(ValueError, match="parent_observed_at cannot precede"):
        RawCaptureArtifact.from_mapping(payload)


def test_artifact_creation_before_parent_observation_fails_closed():
    payload = artifact_payload()
    payload["artifact_created_at_utc"] = "2026-09-10T10:00:01Z"
    with pytest.raises(ValueError, match="cannot precede parent observation"):
        RawCaptureArtifact.from_mapping(payload)


def test_exact_artifact_bytes_are_sealed_not_semantic_reencoding(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        load_sealed_raw_capture(artifact_path, manifest_path)


def test_manifest_capture_id_mismatch_fails_closed(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["capture_id"] = "other-capture"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest capture_id mismatch"):
        load_sealed_raw_capture(artifact_path, manifest_path)


def test_manifest_cannot_claim_seal_before_artifact_creation(tmp_path):
    artifact_path, manifest_path = write_sealed(
        tmp_path,
        sealed_at="2026-09-10T10:00:03Z",
    )
    with pytest.raises(ValueError, match="sealed_at cannot precede"):
        load_sealed_raw_capture(artifact_path, manifest_path)


def test_capture_encoder_rejects_unknown_python_object_instead_of_default_str():
    payload = artifact_payload()
    payload["observations"][0]["raw_payload"]["unknown"] = object()
    with pytest.raises(ValueError, match="unsupported raw type object"):
        encode_raw_capture(payload)


def test_capture_encoder_rejects_non_finite_float():
    payload = artifact_payload()
    payload["observations"][0]["raw_payload"]["bad"] = float("nan")
    with pytest.raises(ValueError, match="non-finite float"):
        encode_raw_capture(payload)


def test_strict_loader_rejects_non_finite_json_constant(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    raw = artifact_path.read_text().replace('"volume":12345', '"volume":NaN')
    artifact_path.write_text(raw)
    manifest = json.loads(manifest_path.read_text())
    manifest["artifact_sha256"] = sha256(artifact_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        load_sealed_raw_capture(artifact_path, manifest_path)


def test_serialization_diagnostic_blocks_pit_eligibility(tmp_path):
    payload = artifact_payload(diagnostics=["numpy.int64 explicitly normalized upstream"])
    artifact_path, manifest_path = write_sealed(tmp_path, payload)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    with pytest.raises(ValueError, match="not eligible for point-in-time"):
        sealed.pit_binding("history-K_15M-1")


def test_duplicate_observation_identity_fails_closed():
    payload = artifact_payload()
    payload["observations"].append(dict(payload["observations"][0]))
    with pytest.raises(ValueError, match="observation_id values must be unique"):
        RawCaptureArtifact.from_mapping(payload)


def test_raw_payload_is_recursively_immutable(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    observation = sealed.artifact.observation("history-K_15M-1")
    with pytest.raises(TypeError):
        observation.raw_payload["raw_rows"][0]["close"] = 999


def test_row_normalization_lineage_binds_artifact_observation_and_row(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    lineage = build_row_normalization_lineage(
        sealed,
        observation_id="history-K_15M-1",
        row_index=1,
        normalizer_version="futu-history-v1",
        normalizer_sha256=NORMALIZER_SHA,
        derived_event_id="event:qqq:2026-09-09T10:00",
        expected_artifact_sha256=sealed.manifest.artifact_sha256,
    )
    assert lineage.artifact_sha256 == sealed.manifest.artifact_sha256
    assert lineage.raw_path.endswith("raw_rows[1]")
    assert len(lineage.lineage_digest) == 64


def test_wrong_artifact_digest_cannot_be_used_for_normalization(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    with pytest.raises(ValueError, match="wrong raw artifact digest"):
        build_row_normalization_lineage(
            sealed,
            observation_id="history-K_15M-1",
            row_index=0,
            normalizer_version="futu-history-v1",
            normalizer_sha256=NORMALIZER_SHA,
            derived_event_id="event:1",
            expected_artifact_sha256="0" * 64,
        )


@pytest.mark.parametrize("row_index", [-1, 2, True])
def test_invalid_raw_row_index_fails_closed(tmp_path, row_index):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    with pytest.raises(ValueError, match="row index is out of range"):
        build_row_normalization_lineage(
            sealed,
            observation_id="history-K_15M-1",
            row_index=row_index,
            normalizer_version="futu-history-v1",
            normalizer_sha256=NORMALIZER_SHA,
            derived_event_id="event:1",
        )


def test_normalizer_version_change_creates_distinct_lineage(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    first = build_row_normalization_lineage(
        sealed,
        observation_id="history-K_15M-1",
        row_index=0,
        normalizer_version="futu-history-v1",
        normalizer_sha256=NORMALIZER_SHA,
        derived_event_id="event:1",
    )
    second = build_row_normalization_lineage(
        sealed,
        observation_id="history-K_15M-1",
        row_index=0,
        normalizer_version="futu-history-v2",
        normalizer_sha256=NORMALIZER_SHA,
        derived_event_id="event:1",
    )
    assert first.lineage_digest != second.lineage_digest


def test_unknown_observation_cannot_be_normalized(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    with pytest.raises(ValueError, match="unknown observation_id"):
        build_row_normalization_lineage(
            sealed,
            observation_id="missing",
            row_index=0,
            normalizer_version="v1",
            normalizer_sha256=NORMALIZER_SHA,
            derived_event_id="event:1",
        )


def test_legacy_manifest_is_not_authority_receipt_anchored(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    assert sealed.manifest.schema_version == RAW_CAPTURE_MANIFEST_VERSION
    assert not sealed.manifest.is_authority_receipt_anchored
    assert sealed.manifest.authority_receipt_sha256 is None


def test_legacy_manifest_cannot_carry_an_authority_receipt_anchor():
    with pytest.raises(ValueError, match="cannot carry an authority receipt anchor"):
        RawCaptureManifest(
            schema_version=RAW_CAPTURE_MANIFEST_VERSION,
            capture_id="capture-x",
            artifact_filename="capture.json",
            artifact_sha256="a" * 64,
            sealed_at=datetime(2026, 9, 10, 10, 0, 5, tzinfo=UTC),
            authority_receipt_sha256="b" * 64,
        )


def test_v02_manifest_requires_valid_hex_authority_receipt_anchor():
    with pytest.raises(ValueError, match="authority_receipt_sha256"):
        RawCaptureManifest(
            schema_version=RAW_CAPTURE_MANIFEST_VERSION_V2,
            capture_id="capture-x",
            artifact_filename="capture.json",
            artifact_sha256="a" * 64,
            sealed_at=datetime(2026, 9, 10, 10, 0, 5, tzinfo=UTC),
            authority_receipt_sha256=None,
        )


def test_v02_manifest_round_trips_with_authority_receipt_anchor(tmp_path):
    payload = artifact_payload()
    artifact_bytes = encode_raw_capture(payload)
    artifact_path = tmp_path / "capture.json"
    artifact_path.write_bytes(artifact_bytes)
    anchor = "c" * 64
    manifest = {
        "schema_version": RAW_CAPTURE_MANIFEST_VERSION_V2,
        "capture_id": payload["capture_id"],
        "artifact_filename": artifact_path.name,
        "artifact_sha256": sha256(artifact_bytes).hexdigest(),
        "sealed_at_utc": "2026-09-10T10:00:05Z",
        "authority_receipt_sha256": anchor,
    }
    manifest_path = tmp_path / "capture.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    assert sealed.manifest.is_authority_receipt_anchored
    assert sealed.manifest.authority_receipt_sha256 == anchor


def test_verify_authority_receipt_anchor_fails_closed_for_legacy_manifest(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    with pytest.raises(ValueError, match="no contemporaneous authority receipt anchor"):
        sealed.verify_authority_receipt_anchor(b'{"anything":"goes"}')


def test_verify_authority_receipt_anchor_detects_mismatch(tmp_path):
    payload = artifact_payload()
    artifact_bytes = encode_raw_capture(payload)
    artifact_path = tmp_path / "capture.json"
    artifact_path.write_bytes(artifact_bytes)
    receipt_bytes = b'{"fixture":"receipt"}'
    manifest = {
        "schema_version": RAW_CAPTURE_MANIFEST_VERSION_V2,
        "capture_id": payload["capture_id"],
        "artifact_filename": artifact_path.name,
        "artifact_sha256": sha256(artifact_bytes).hexdigest(),
        "sealed_at_utc": "2026-09-10T10:00:05Z",
        "authority_receipt_sha256": sha256(receipt_bytes).hexdigest(),
    }
    manifest_path = tmp_path / "capture.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    sealed.verify_authority_receipt_anchor(receipt_bytes)
    with pytest.raises(ValueError, match="anchor mismatch"):
        sealed.verify_authority_receipt_anchor(receipt_bytes + b"\n")


def test_pre_seal_helper_parses_artifact_and_digest_without_a_manifest():
    payload = artifact_payload()
    artifact_bytes = encode_raw_capture(payload)
    artifact, digest = parse_and_digest_raw_capture_artifact(artifact_bytes)
    assert digest == sha256(artifact_bytes).hexdigest()
    assert artifact.capture_id == payload["capture_id"]


def test_pre_seal_helper_rejects_empty_bytes():
    with pytest.raises(ValueError, match="artifact bytes are required"):
        parse_and_digest_raw_capture_artifact(b"")
