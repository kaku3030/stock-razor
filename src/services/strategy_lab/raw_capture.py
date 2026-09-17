"""Raw provider-capture integrity contracts for Strategy Lab A4 / Run B2.

This module is research/evidence infrastructure only. It seals exact capture
bytes, separates request/response/parent observation clocks, and provides
normalization lineage. It does not establish provider Currentness, routing,
SHADOW_ACTIVE, CORE, LIVE, strategy, broker, or trading authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from json import dumps
import math
from pathlib import Path
from typing import Any, Mapping

from .replay_contract import aware_utc, deep_freeze, stable_hash
from .strict_json import loads_strict_json

RAW_CAPTURE_SCHEMA_VERSION = "raw-provider-capture-v0.1"
RAW_CAPTURE_MANIFEST_VERSION = "raw-provider-capture-manifest-v0.1"
RAW_CAPTURE_MANIFEST_VERSION_V2 = "raw-provider-capture-manifest-v0.2"
NORMALIZATION_LINEAGE_VERSION = "raw-normalization-lineage-v0.1"

STATUS_OK = "OK"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_SDK_ERROR = "SDK_ERROR"
STATUS_EXCEPTION = "EXCEPTION"
_ALLOWED_STATUSES = frozenset({STATUS_OK, STATUS_TIMEOUT, STATUS_SDK_ERROR, STATUS_EXCEPTION})

_ARTIFACT_KEYS = frozenset(
    {
        "schema_version",
        "capture_id",
        "provider_label",
        "capture_tool_repository",
        "capture_tool_path",
        "capture_tool_commit_sha",
        "capture_tool_blob_sha",
        "sdk_version",
        "opend_version",
        "artifact_created_at_utc",
        "observations",
    }
)
_OBSERVATION_KEYS = frozenset(
    {
        "observation_id",
        "status",
        "operation",
        "symbol",
        "ktype",
        "session",
        "autype",
        "request_params",
        "request_started_at_utc",
        "response_received_at_utc",
        "parent_observed_at_utc",
        "raw_payload",
        "serialization_diagnostics",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "capture_id",
        "artifact_filename",
        "artifact_sha256",
        "sealed_at_utc",
    }
)
_MANIFEST_KEYS_V2 = _MANIFEST_KEYS | {"authority_receipt_sha256"}


def _exact_keys(payload: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(payload)
    if actual != expected:
        raise ValueError(
            f"{label} schema mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _trimmed(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    return value


def _hex(value: Any, name: str, length: int) -> str:
    text = _trimmed(value, name)
    if len(text) != length or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{name} must be {length}-char lowercase hex")
    return text


def _parse_aware(value: Any, name: str) -> datetime:
    text = _trimmed(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601 datetime") from exc
    result = aware_utc(parsed, name)
    if result is None:
        raise ValueError(f"{name} must be timezone-aware")
    return result


def _optional_aware(value: Any, name: str) -> datetime | None:
    if value is None:
        return None
    return _parse_aware(value, name)


def _json_safe_clone(value: Any, path: str = "$raw") -> Any:
    """Return JSON-native data without silent coercion or ``default=str``."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains non-finite float")
        return value
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains non-string mapping key")
            output[key] = _json_safe_clone(item, f"{path}.{key}")
        return output
    if isinstance(value, tuple):
        raise ValueError(f"{path} contains non-JSON-native tuple")
    if isinstance(value, list):
        return [_json_safe_clone(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise ValueError(f"{path} contains unsupported raw type {type(value).__name__}")


def _strict_json_loads(raw: bytes, label: str) -> Mapping[str, Any]:
    """Apply the accepted shared strict parser plus A4's object-root contract."""

    payload = loads_strict_json(raw, label)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} root must be an object")
    return payload


def encode_raw_capture(payload: Mapping[str, Any]) -> bytes:
    """Encode capture JSON deterministically and fail on unknown/coerced types."""

    safe = _json_safe_clone(payload)
    return dumps(
        safe,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class RawCaptureObservation:
    observation_id: str
    status: str
    operation: str
    symbol: str
    ktype: str
    session: str
    autype: str
    request_params: Mapping[str, Any]
    request_started_at: datetime
    response_received_at: datetime | None
    parent_observed_at: datetime
    raw_payload: Any
    serialization_diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("observation_id", "operation", "symbol", "ktype", "session", "autype"):
            _trimmed(getattr(self, name), name)
        if self.status not in _ALLOWED_STATUSES:
            raise ValueError(f"unsupported observation status: {self.status}")

        request_started = aware_utc(self.request_started_at, "request_started_at")
        parent_observed = aware_utc(self.parent_observed_at, "parent_observed_at")
        response_received = aware_utc(self.response_received_at, "response_received_at")
        assert request_started is not None and parent_observed is not None
        object.__setattr__(self, "request_started_at", request_started)
        object.__setattr__(self, "response_received_at", response_received)
        object.__setattr__(self, "parent_observed_at", parent_observed)

        if response_received is not None and response_received < request_started:
            raise ValueError("response_received_at cannot precede request_started_at")
        if response_received is not None and parent_observed < response_received:
            raise ValueError("parent_observed_at cannot precede response_received_at")
        if response_received is None and parent_observed < request_started:
            raise ValueError("parent_observed_at cannot precede request_started_at")
        if self.status == STATUS_OK and response_received is None:
            raise ValueError("successful observation requires response_received_at")

        if not isinstance(self.request_params, Mapping):
            raise ValueError("request_params must be an object")
        object.__setattr__(self, "request_params", deep_freeze(_json_safe_clone(self.request_params)))
        object.__setattr__(self, "raw_payload", deep_freeze(_json_safe_clone(self.raw_payload)))

        diagnostics = tuple(self.serialization_diagnostics)
        for item in diagnostics:
            _trimmed(item, "serialization_diagnostic")
        object.__setattr__(self, "serialization_diagnostics", diagnostics)

    @property
    def capture_complete(self) -> bool:
        """Structural completeness for the current history-capture research slice.

        This deliberately proves only representable capture shape. It does not
        infer provider accuracy, session completeness, bar semantics, or
        Currentness.
        """

        if self.operation != "history":
            return False
        if not isinstance(self.raw_payload, Mapping):
            return False
        rows = self.raw_payload.get("raw_rows")
        if not isinstance(rows, tuple):
            return False
        return all(isinstance(row, Mapping) for row in rows)

    @property
    def pit_eligible(self) -> bool:
        return (
            self.status == STATUS_OK
            and self.response_received_at is not None
            and not self.serialization_diagnostics
            and self.capture_complete
        )

    @property
    def available_at(self) -> datetime | None:
        return self.response_received_at if self.pit_eligible else None

    @property
    def observed_at(self) -> datetime | None:
        return self.parent_observed_at if self.pit_eligible else None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RawCaptureObservation":
        _exact_keys(payload, _OBSERVATION_KEYS, "observation")
        diagnostics = payload["serialization_diagnostics"]
        if not isinstance(diagnostics, list):
            raise ValueError("serialization_diagnostics must be a list")
        return cls(
            observation_id=payload["observation_id"],
            status=payload["status"],
            operation=payload["operation"],
            symbol=payload["symbol"],
            ktype=payload["ktype"],
            session=payload["session"],
            autype=payload["autype"],
            request_params=payload["request_params"],
            request_started_at=_parse_aware(payload["request_started_at_utc"], "request_started_at_utc"),
            response_received_at=_optional_aware(
                payload["response_received_at_utc"], "response_received_at_utc"
            ),
            parent_observed_at=_parse_aware(
                payload["parent_observed_at_utc"], "parent_observed_at_utc"
            ),
            raw_payload=payload["raw_payload"],
            serialization_diagnostics=tuple(diagnostics),
        )


@dataclass(frozen=True)
class RawCaptureArtifact:
    schema_version: str
    capture_id: str
    provider_label: str
    capture_tool_repository: str
    capture_tool_path: str
    capture_tool_commit_sha: str
    capture_tool_blob_sha: str
    sdk_version: str
    opend_version: str
    artifact_created_at: datetime
    observations: tuple[RawCaptureObservation, ...]

    def __post_init__(self) -> None:
        if self.schema_version != RAW_CAPTURE_SCHEMA_VERSION:
            raise ValueError(f"unsupported raw capture schema: {self.schema_version}")
        for name in (
            "capture_id",
            "provider_label",
            "capture_tool_repository",
            "capture_tool_path",
            "sdk_version",
            "opend_version",
        ):
            _trimmed(getattr(self, name), name)
        _hex(self.capture_tool_commit_sha, "capture_tool_commit_sha", 40)
        _hex(self.capture_tool_blob_sha, "capture_tool_blob_sha", 40)

        created = aware_utc(self.artifact_created_at, "artifact_created_at")
        assert created is not None
        object.__setattr__(self, "artifact_created_at", created)

        try:
            observations = tuple(self.observations)
        except TypeError as exc:
            raise ValueError("observations must be an iterable of RawCaptureObservation") from exc
        if not observations:
            raise ValueError("raw capture requires at least one observation")
        if any(not isinstance(item, RawCaptureObservation) for item in observations):
            raise ValueError("observations must contain only RawCaptureObservation")
        object.__setattr__(self, "observations", observations)

        identifiers = [item.observation_id for item in observations]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("observation_id values must be unique")
        if any(item.parent_observed_at > created for item in observations):
            raise ValueError("artifact_created_at cannot precede parent observation")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RawCaptureArtifact":
        _exact_keys(payload, _ARTIFACT_KEYS, "raw capture")
        observations = payload["observations"]
        if not isinstance(observations, list):
            raise ValueError("observations must be a list")
        return cls(
            schema_version=payload["schema_version"],
            capture_id=payload["capture_id"],
            provider_label=payload["provider_label"],
            capture_tool_repository=payload["capture_tool_repository"],
            capture_tool_path=payload["capture_tool_path"],
            capture_tool_commit_sha=payload["capture_tool_commit_sha"],
            capture_tool_blob_sha=payload["capture_tool_blob_sha"],
            sdk_version=payload["sdk_version"],
            opend_version=payload["opend_version"],
            artifact_created_at=_parse_aware(payload["artifact_created_at_utc"], "artifact_created_at_utc"),
            observations=tuple(RawCaptureObservation.from_mapping(item) for item in observations),
        )

    def observation(self, observation_id: str) -> RawCaptureObservation:
        for item in self.observations:
            if item.observation_id == observation_id:
                return item
        raise ValueError(f"unknown observation_id: {observation_id}")


@dataclass(frozen=True)
class RawCaptureManifest:
    schema_version: str
    capture_id: str
    artifact_filename: str
    artifact_sha256: str
    sealed_at: datetime
    authority_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version not in (RAW_CAPTURE_MANIFEST_VERSION, RAW_CAPTURE_MANIFEST_VERSION_V2):
            raise ValueError(f"unsupported raw capture manifest: {self.schema_version}")
        _trimmed(self.capture_id, "capture_id")
        filename = _trimmed(self.artifact_filename, "artifact_filename")
        if Path(filename).name != filename:
            raise ValueError("artifact_filename must be a basename")
        _hex(self.artifact_sha256, "artifact_sha256", 64)
        sealed = aware_utc(self.sealed_at, "sealed_at")
        assert sealed is not None
        object.__setattr__(self, "sealed_at", sealed)

        if self.schema_version == RAW_CAPTURE_MANIFEST_VERSION_V2:
            _hex(self.authority_receipt_sha256, "authority_receipt_sha256", 64)
        elif self.authority_receipt_sha256 is not None:
            # A legacy manifest can never carry a contemporaneous anchor: if it
            # did not seal one originally, no later construction may add it.
            raise ValueError("legacy raw capture manifest cannot carry an authority receipt anchor")

    @property
    def is_authority_receipt_anchored(self) -> bool:
        return self.schema_version == RAW_CAPTURE_MANIFEST_VERSION_V2

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RawCaptureManifest":
        expected = _MANIFEST_KEYS_V2 if payload.get("schema_version") == RAW_CAPTURE_MANIFEST_VERSION_V2 else _MANIFEST_KEYS
        _exact_keys(payload, expected, "raw capture manifest")
        return cls(
            schema_version=payload["schema_version"],
            capture_id=payload["capture_id"],
            artifact_filename=payload["artifact_filename"],
            artifact_sha256=payload["artifact_sha256"],
            sealed_at=_parse_aware(payload["sealed_at_utc"], "sealed_at_utc"),
            authority_receipt_sha256=payload.get("authority_receipt_sha256"),
        )


class SealedRawCapture:
    """A capture whose semantic object is always rooted in verified exact bytes.

    Ordinary direct construction is intentionally forbidden. The loader/factory
    binds exact bytes to a manifest digest first, then every access revalidates
    that binding before exposing the parsed artifact.
    """

    __slots__ = ("_artifact_bytes", "_manifest")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("SealedRawCapture requires the verified loader/factory path")

    @classmethod
    def _from_verified_bytes(
        cls,
        artifact_bytes: bytes,
        manifest: RawCaptureManifest,
    ) -> "SealedRawCapture":
        actual_digest = sha256(artifact_bytes).hexdigest()
        if actual_digest != manifest.artifact_sha256:
            raise ValueError("raw capture artifact digest mismatch")
        artifact = RawCaptureArtifact.from_mapping(
            _strict_json_loads(artifact_bytes, "raw capture artifact")
        )
        if artifact.capture_id != manifest.capture_id:
            raise ValueError("manifest capture_id mismatch")
        if manifest.sealed_at < artifact.artifact_created_at:
            raise ValueError("manifest sealed_at cannot precede artifact_created_at")

        instance = object.__new__(cls)
        object.__setattr__(instance, "_artifact_bytes", bytes(artifact_bytes))
        object.__setattr__(instance, "_manifest", manifest)
        return instance

    def _verified_artifact(self) -> RawCaptureArtifact:
        try:
            artifact_bytes = self._artifact_bytes
            manifest = self._manifest
        except AttributeError as exc:
            raise ValueError("sealed raw capture is not verified") from exc
        actual_digest = sha256(artifact_bytes).hexdigest()
        if actual_digest != manifest.artifact_sha256:
            raise ValueError("sealed raw capture digest verification failed")
        artifact = RawCaptureArtifact.from_mapping(
            _strict_json_loads(artifact_bytes, "raw capture artifact")
        )
        if artifact.capture_id != manifest.capture_id:
            raise ValueError("sealed raw capture capture_id mismatch")
        if manifest.sealed_at < artifact.artifact_created_at:
            raise ValueError("sealed raw capture chronology invalid")
        return artifact

    @property
    def artifact(self) -> RawCaptureArtifact:
        return self._verified_artifact()

    @property
    def manifest(self) -> RawCaptureManifest:
        try:
            return self._manifest
        except AttributeError as exc:
            raise ValueError("sealed raw capture is not verified") from exc

    def pit_binding(self, observation_id: str) -> tuple[datetime, datetime]:
        return pit_binding_for_observation(self._verified_artifact(), observation_id)

    def verify_authority_receipt_anchor(self, receipt_bytes: bytes) -> None:
        """Prove ``receipt_bytes`` match the manifest's contemporaneous anchor.

        A legacy (v0.1) manifest never sealed an anchor, so it fails closed
        here unconditionally: no later receipt, however internally valid,
        can retroactively become the one this capture was sealed with.
        """

        manifest = self.manifest
        if not manifest.is_authority_receipt_anchored:
            raise ValueError(
                "raw capture manifest has no contemporaneous authority receipt "
                "anchor (legacy manifest version); a later receipt cannot be "
                "retroactively bound to this capture"
            )
        if not isinstance(receipt_bytes, bytes) or not receipt_bytes:
            raise ValueError("authority receipt bytes are required for anchor verification")
        actual = sha256(receipt_bytes).hexdigest()
        if actual != manifest.authority_receipt_sha256:
            raise ValueError(
                "authority receipt anchor mismatch: receipt bytes do not match "
                "the manifest's sealed anchor"
            )


def pit_binding_for_observation(
    artifact: RawCaptureArtifact, observation_id: str
) -> tuple[datetime, datetime]:
    observation = artifact.observation(observation_id)
    if not observation.pit_eligible:
        raise ValueError("observation is not eligible for point-in-time normalization")
    assert observation.available_at is not None and observation.observed_at is not None
    return observation.available_at, observation.observed_at


def parse_and_digest_raw_capture_artifact(artifact_bytes: bytes) -> tuple[RawCaptureArtifact, str]:
    """Pure pre-seal helper: derive verified artifact facts directly from bytes.

    Exists so capture-time evidence (e.g. an authority receipt) can be built
    from already-validated raw bytes *before* a manifest exists, keeping the
    manifest anchor's hash dependency acyclic (bytes -> receipt -> anchor,
    never the reverse).
    """

    if not isinstance(artifact_bytes, bytes) or not artifact_bytes:
        raise ValueError("raw capture artifact bytes are required")
    digest = sha256(artifact_bytes).hexdigest()
    artifact = RawCaptureArtifact.from_mapping(_strict_json_loads(artifact_bytes, "raw capture artifact"))
    return artifact, digest


def load_sealed_raw_capture(
    artifact_path: str | Path,
    manifest_path: str | Path,
) -> SealedRawCapture:
    artifact_path = Path(artifact_path)
    manifest_path = Path(manifest_path)
    artifact_bytes = artifact_path.read_bytes()
    manifest = RawCaptureManifest.from_mapping(
        _strict_json_loads(manifest_path.read_bytes(), "raw capture manifest")
    )
    if manifest.artifact_filename != artifact_path.name:
        raise ValueError("manifest artifact filename mismatch")
    return SealedRawCapture._from_verified_bytes(artifact_bytes, manifest)


@dataclass(frozen=True)
class NormalizationLineage:
    schema_version: str
    artifact_sha256: str
    capture_id: str
    observation_id: str
    raw_path: str
    normalizer_version: str
    normalizer_sha256: str
    derived_event_id: str
    lineage_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != NORMALIZATION_LINEAGE_VERSION:
            raise ValueError(f"unsupported normalization lineage: {self.schema_version}")
        _hex(self.artifact_sha256, "artifact_sha256", 64)
        _hex(self.normalizer_sha256, "normalizer_sha256", 64)
        for name in (
            "capture_id",
            "observation_id",
            "raw_path",
            "normalizer_version",
            "derived_event_id",
        ):
            _trimmed(getattr(self, name), name)
        _hex(self.lineage_digest, "lineage_digest", 64)
        if self.lineage_digest != stable_hash(self.digest_payload()):
            raise ValueError("normalization lineage digest mismatch")

    def digest_payload(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "artifact_sha256": self.artifact_sha256,
            "capture_id": self.capture_id,
            "observation_id": self.observation_id,
            "raw_path": self.raw_path,
            "normalizer_version": self.normalizer_version,
            "normalizer_sha256": self.normalizer_sha256,
            "derived_event_id": self.derived_event_id,
        }


def build_row_normalization_lineage(
    sealed: SealedRawCapture,
    *,
    observation_id: str,
    row_index: int,
    normalizer_version: str,
    normalizer_sha256: str,
    derived_event_id: str,
    expected_artifact_sha256: str | None = None,
) -> NormalizationLineage:
    if not isinstance(sealed, SealedRawCapture):
        raise ValueError("normalization requires a verified SealedRawCapture")
    artifact = sealed._verified_artifact()
    manifest = sealed.manifest
    if expected_artifact_sha256 is not None and expected_artifact_sha256 != manifest.artifact_sha256:
        raise ValueError("normalization requested against wrong raw artifact digest")

    observation = artifact.observation(observation_id)
    if not observation.pit_eligible:
        raise ValueError("observation is not eligible for normalization")
    payload = observation.raw_payload
    if not isinstance(payload, Mapping):
        raise ValueError("raw payload must be an object with raw_rows")
    rows = payload.get("raw_rows")
    if not isinstance(rows, tuple):
        raise ValueError("raw payload raw_rows must be a list")
    if isinstance(row_index, bool) or not isinstance(row_index, int) or row_index < 0 or row_index >= len(rows):
        raise ValueError("raw row index is out of range")

    raw_path = f"observations[{observation_id}].raw_payload.raw_rows[{row_index}]"
    payload_for_digest = {
        "schema_version": NORMALIZATION_LINEAGE_VERSION,
        "artifact_sha256": manifest.artifact_sha256,
        "capture_id": artifact.capture_id,
        "observation_id": observation_id,
        "raw_path": raw_path,
        "normalizer_version": _trimmed(normalizer_version, "normalizer_version"),
        "normalizer_sha256": _hex(normalizer_sha256, "normalizer_sha256", 64),
        "derived_event_id": _trimmed(derived_event_id, "derived_event_id"),
    }
    return NormalizationLineage(
        **payload_for_digest,
        lineage_digest=stable_hash(payload_for_digest),
    )
