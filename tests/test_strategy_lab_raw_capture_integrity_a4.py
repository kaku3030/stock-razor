from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from src.services.strategy_lab.raw_capture import (
    RAW_CAPTURE_MANIFEST_VERSION,
    RawCaptureArtifact,
    RawCaptureObservation,
    SealedRawCapture,
    build_row_normalization_lineage,
    encode_raw_capture,
    load_sealed_raw_capture,
)

UTC = timezone.utc
TOOL_COMMIT = "05b872b2da9eb077070b4aa3ef1261671f3825ce"
TOOL_BLOB = "890e3bdca155e6eb65095d9ba7160aeba78a0f48"
NORMALIZER_SHA = "1" * 64


def artifact_payload(raw_payload=None):
    if raw_payload is None:
        raw_payload = {
            "raw_rows": [
                {
                    "time_key": "2026-09-09 09:45:00",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 12345,
                }
            ]
        }
    return {
        "schema_version": "raw-provider-capture-v0.1",
        "capture_id": "capture-1",
        "provider_label": "FUTU_EVIDENCE_ONLY",
        "capture_tool_repository": "kaku3030/stock-razor",
        "capture_tool_path": "tools/provider_semantics/futu/kline_snapshot_probe.py",
        "capture_tool_commit_sha": TOOL_COMMIT,
        "capture_tool_blob_sha": TOOL_BLOB,
        "sdk_version": "10",
        "opend_version": "1010",
        "artifact_created_at_utc": "2026-09-10T10:00:04Z",
        "observations": [
            {
                "observation_id": "obs-1",
                "status": "OK",
                "operation": "history",
                "symbol": "US.QQQ",
                "ktype": "K_15M",
                "session": "RTH",
                "autype": "NONE",
                "request_params": {},
                "request_started_at_utc": "2026-09-10T10:00:00Z",
                "response_received_at_utc": "2026-09-10T10:00:01Z",
                "parent_observed_at_utc": "2026-09-10T10:00:02Z",
                "raw_payload": raw_payload,
                "serialization_diagnostics": [],
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
    return artifact_path, manifest_path


def _rewrite_manifest_digest(manifest_path, artifact_path):
    manifest = json.loads(manifest_path.read_text())
    manifest["artifact_sha256"] = sha256(artifact_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_verified_loader_round_trip_and_lineage(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    available_at, observed_at = sealed.pit_binding("obs-1")
    assert available_at == datetime(2026, 9, 10, 10, 0, 1, tzinfo=UTC)
    assert observed_at == datetime(2026, 9, 10, 10, 0, 2, tzinfo=UTC)
    lineage = build_row_normalization_lineage(
        sealed,
        observation_id="obs-1",
        row_index=0,
        normalizer_version="v1",
        normalizer_sha256=NORMALIZER_SHA,
        derived_event_id="event:1",
    )
    assert lineage.artifact_sha256 == sealed.manifest.artifact_sha256


def test_direct_sealed_constructor_cannot_bypass_byte_verification(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    valid = load_sealed_raw_capture(artifact_path, manifest_path)
    with pytest.raises(TypeError, match="verified loader"):
        SealedRawCapture(valid.artifact, valid.manifest)


def test_uninitialized_sealed_object_cannot_mint_lineage():
    synthetic = object.__new__(SealedRawCapture)
    with pytest.raises(ValueError, match="not verified"):
        build_row_normalization_lineage(
            synthetic,
            observation_id="obs-1",
            row_index=0,
            normalizer_version="v1",
            normalizer_sha256=NORMALIZER_SHA,
            derived_event_id="event:1",
        )


def test_direct_artifact_observation_membership_is_copied_and_type_checked():
    observation = RawCaptureObservation.from_mapping(artifact_payload()["observations"][0])
    original = [observation]
    artifact = RawCaptureArtifact(
        schema_version="raw-provider-capture-v0.1",
        capture_id="capture-1",
        provider_label="P",
        capture_tool_repository="r",
        capture_tool_path="p",
        capture_tool_commit_sha=TOOL_COMMIT,
        capture_tool_blob_sha=TOOL_BLOB,
        sdk_version="s",
        opend_version="o",
        artifact_created_at=datetime(2026, 9, 10, 10, 0, 4, tzinfo=UTC),
        observations=original,
    )
    original.clear()
    assert isinstance(artifact.observations, tuple)
    assert len(artifact.observations) == 1

    with pytest.raises(ValueError, match="only RawCaptureObservation"):
        RawCaptureArtifact(
            schema_version="raw-provider-capture-v0.1",
            capture_id="capture-1",
            provider_label="P",
            capture_tool_repository="r",
            capture_tool_path="p",
            capture_tool_commit_sha=TOOL_COMMIT,
            capture_tool_blob_sha=TOOL_BLOB,
            sdk_version="s",
            opend_version="o",
            artifact_created_at=datetime(2026, 9, 10, 10, 0, 4, tzinfo=UTC),
            observations=[object()],
        )


@pytest.mark.parametrize(
    "raw_payload",
    [
        None,
        {},
        {"raw_rows": {}},
        {"raw_rows": [1]},
    ],
)
def test_incomplete_ok_capture_cannot_receive_pit_binding(tmp_path, raw_payload):
    payload = artifact_payload({"sentinel": "temporary"})
    payload["observations"][0]["raw_payload"] = raw_payload
    artifact_path, manifest_path = write_sealed(tmp_path, payload)
    sealed = load_sealed_raw_capture(artifact_path, manifest_path)
    with pytest.raises(ValueError, match="not eligible"):
        sealed.pit_binding("obs-1")


def test_duplicate_top_level_artifact_key_rejected_even_with_matching_digest(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    raw = artifact_path.read_text().replace(
        '"capture_id":"capture-1"',
        '"capture_id":"capture-1","capture_id":"evil"',
        1,
    )
    artifact_path.write_text(raw)
    _rewrite_manifest_digest(manifest_path, artifact_path)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_sealed_raw_capture(artifact_path, manifest_path)


@pytest.mark.parametrize(
    "needle,replacement",
    [
        ('"status":"OK"', '"status":"OK","status":"TIMEOUT"'),
        ('"request_params":{}', '"request_params":{"x":1,"x":2}'),
        ('"raw_payload":{"raw_rows"', '"raw_payload":{"x":1,"x":2,"raw_rows"'),
    ],
)
def test_duplicate_nested_artifact_keys_rejected_at_every_depth(
    tmp_path, needle, replacement
):
    artifact_path, manifest_path = write_sealed(tmp_path)
    raw = artifact_path.read_text().replace(needle, replacement, 1)
    assert raw != artifact_path.read_text()
    artifact_path.write_text(raw)
    _rewrite_manifest_digest(manifest_path, artifact_path)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_sealed_raw_capture(artifact_path, manifest_path)


def test_duplicate_manifest_key_rejected(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    raw = manifest_path.read_text().replace(
        '"capture_id": "capture-1"',
        '"capture_id": "capture-1", "capture_id": "evil"',
        1,
    )
    manifest_path.write_text(raw)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_sealed_raw_capture(artifact_path, manifest_path)


def test_tuple_raw_input_rejected_instead_of_silent_array_coercion():
    payload = artifact_payload()
    payload["observations"][0]["raw_payload"]["raw_rows"] = tuple(
        payload["observations"][0]["raw_payload"]["raw_rows"]
    )
    with pytest.raises(ValueError, match="non-JSON-native tuple"):
        encode_raw_capture(payload)


def test_changed_bytes_with_stale_manifest_digest_still_fail_seal(tmp_path):
    artifact_path, manifest_path = write_sealed(tmp_path)
    artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        load_sealed_raw_capture(artifact_path, manifest_path)
