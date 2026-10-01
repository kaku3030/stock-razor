"""Point-in-time recorded market fixture contracts for Strategy Lab Run B.

Run B is DATA/TEST/SHADOW infrastructure only. Historical provider/source
authority is captured with each fixture and is never reconstructed solely from
the current mutable provider registry. This module does not grant Currentness,
routing, SHADOW_ACTIVE, CORE, LIVE, notification, broker, or trading authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .replay_baseline import replay
from .replay_contract import (
    EventRecord,
    ReplayResult,
    SourceAuthorityResolution,
    SourceAuthorityResolver,
    aware_utc,
    deep_freeze,
    stable_hash,
)
from .strict_json import load_strict_json

AUTHORITY_SCHEMA_VERSION = "recorded-authority-v0.1"
FIXTURE_SCHEMA_VERSION = "recorded-market-fixture-v0.1"
AUTHORITY_MODE_EMBEDDED = "EMBEDDED"
REPRESENTATION_NORMALIZED_LICENSED_CSV = "NORMALIZED_FROM_LICENSED_PUBLIC_CSV"

BAR_TIMESTAMP_SOURCE_DECLARED = "SOURCE_DECLARED_DATETIME_ONLY"
AVAILABILITY_CONSERVATIVE_CAPTURE_SEAL = "CONSERVATIVE_CAPTURE_SEAL"

AUTHORITY_DRIFT_NOT_CHECKED = "CURRENT_AUTHORITY_NOT_CHECKED"
AUTHORITY_DRIFT_MATCH = "CURRENT_AUTHORITY_MATCH"
AUTHORITY_DRIFT_MISSING = "CURRENT_AUTHORITY_MISSING"
AUTHORITY_DRIFT_DETECTED = "CURRENT_AUTHORITY_DRIFT"

_AUTHORITY_KEYS = frozenset(
    {
        "schema_version",
        "authority_mode",
        "source_token",
        "endpoint_id",
        "market",
        "adapter_id",
        "upstream_lineage_id",
        "authority_ref",
        "capability_surface",
        "evidence_ref",
        "captured_at",
        "source_commit_sha",
        "source_blob_sha",
        "license_spdx",
        "license_ref",
        "license_blob_sha",
        "digest",
    }
)
_FIXTURE_KEYS = frozenset(
    {
        "schema_version",
        "fixture_id",
        "symbol",
        "interval_label",
        "source_query",
        "query_params",
        "capture_provenance_ref",
        "representation",
        "available_at",
        "observed_at",
        "time_semantics",
        "authority",
        "rows",
        "rows_digest",
        "fixture_digest",
    }
)
_QUERY_PARAM_KEYS = frozenset({"repository", "path", "ref", "lines"})
_TIME_SEMANTIC_KEYS = frozenset(
    {
        "bar_timestamp_semantic",
        "availability_semantic",
        "session_semantics_claimed",
        "source_commit_time",
        "raw_source_slice_lines",
    }
)
_ROW_KEYS = frozenset({"datetime", "open", "high", "low", "close", "volume"})


def _require_exact_keys(payload: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{label} schema mismatch: missing={missing}, extra={extra}")


def _non_empty_trimmed(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    return value


def _aware_required(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a timezone-aware datetime")
    result = aware_utc(value, name)
    if result is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return result


def _parse_aware(value: Any, name: str) -> datetime:
    raw = _non_empty_trimmed(value, name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601 datetime") from exc
    return _aware_required(parsed, name)


def _hex_sha(value: Any, name: str, length: int) -> str:
    text = _non_empty_trimmed(value, name)
    if len(text) != length or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{name} must be {length}-char lowercase hex")
    return text


def _decimal_text(value: Any, name: str, *, allow_zero: bool = True) -> Decimal:
    text = _non_empty_trimmed(value, name)
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be finite decimal text") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be finite decimal text")
    if number < 0 or (not allow_zero and number == 0):
        raise ValueError(f"{name} out of allowed range")
    return number


def _canonical_repository(value: Any) -> str:
    repository = _non_empty_trimmed(value, "query_params.repository")
    parts = repository.split("/")
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("query_params.repository must be canonical owner/repository")
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._")
    if any(any(char not in allowed for char in part) for part in parts):
        raise ValueError("query_params.repository contains unsupported characters")
    if any(part in {".", ".."} for part in parts):
        raise ValueError("query_params.repository must be canonical owner/repository")
    return repository


def _canonical_repo_path(value: Any, name: str) -> str:
    path = _non_empty_trimmed(value, name)
    if path.startswith("/") or "\\" in path or "?" in path or "#" in path:
        raise ValueError(f"{name} must be a canonical relative repository path")
    if any(char.isspace() or ord(char) < 32 for char in path):
        raise ValueError(f"{name} must be a canonical relative repository path")
    segments = path.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"{name} must be a canonical relative repository path")
    return path


def _canonical_line_range(value: Any, name: str) -> tuple[str, int, int]:
    text = _non_empty_trimmed(value, name)
    parts = text.split("-")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"{name} must be canonical positive N-M")
    start, end = (int(part) for part in parts)
    if start <= 0 or end <= 0 or start > end:
        raise ValueError(f"{name} must be canonical positive N-M")
    if parts[0] != str(start) or parts[1] != str(end):
        raise ValueError(f"{name} must be canonical positive N-M")
    return text, start, end


def _canonical_source_query(repository: str, path: str, ref: str, start: int, end: int) -> str:
    return f"github://{repository}/{path}?ref={ref}#L{start}-L{end}"


def _validate_license_ref(value: str, repository: str, ref: str) -> None:
    prefix = f"{repository}:"
    suffix = f"@{ref}"
    if not value.startswith(prefix) or not value.endswith(suffix):
        raise ValueError("license_ref does not bind canonical repository and commit")
    license_path = value[len(prefix) : -len(suffix)]
    _canonical_repo_path(license_path, "authority.license_ref path")


@dataclass(frozen=True)
class RecordedAuthoritySnapshot:
    schema_version: str
    authority_mode: str
    source_token: str
    endpoint_id: str
    market: str
    adapter_id: str
    upstream_lineage_id: str
    authority_ref: str
    capability_surface: str
    evidence_ref: str
    captured_at: datetime
    source_commit_sha: str
    source_blob_sha: str
    license_spdx: str
    license_ref: str
    license_blob_sha: str
    digest: str

    def __post_init__(self) -> None:
        if self.schema_version != AUTHORITY_SCHEMA_VERSION:
            raise ValueError(f"unsupported authority schema: {self.schema_version}")
        if self.authority_mode != AUTHORITY_MODE_EMBEDDED:
            raise ValueError("Run B A3 supports only embedded capture-time authority")
        for field_name in (
            "source_token",
            "endpoint_id",
            "market",
            "adapter_id",
            "upstream_lineage_id",
            "authority_ref",
            "capability_surface",
            "evidence_ref",
            "license_spdx",
            "license_ref",
        ):
            _non_empty_trimmed(getattr(self, field_name), field_name)

        object.__setattr__(self, "captured_at", _aware_required(self.captured_at, "captured_at"))
        _hex_sha(self.source_commit_sha, "source_commit_sha", 40)
        _hex_sha(self.source_blob_sha, "source_blob_sha", 40)
        _hex_sha(self.license_blob_sha, "license_blob_sha", 40)
        _hex_sha(self.digest, "authority.digest", 64)
        if self.digest != stable_hash(self.digest_payload()):
            raise ValueError("recorded authority digest mismatch")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority_mode": self.authority_mode,
            "source_token": self.source_token,
            "endpoint_id": self.endpoint_id,
            "market": self.market,
            "adapter_id": self.adapter_id,
            "upstream_lineage_id": self.upstream_lineage_id,
            "authority_ref": self.authority_ref,
            "capability_surface": self.capability_surface,
            "evidence_ref": self.evidence_ref,
            "captured_at": self.captured_at,
            "source_commit_sha": self.source_commit_sha,
            "source_blob_sha": self.source_blob_sha,
            "license_spdx": self.license_spdx,
            "license_ref": self.license_ref,
            "license_blob_sha": self.license_blob_sha,
        }

    def canonical_payload(self) -> dict[str, Any]:
        return self.digest_payload() | {"digest": self.digest}

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RecordedAuthoritySnapshot":
        _require_exact_keys(payload, _AUTHORITY_KEYS, "authority")
        return cls(
            schema_version=payload["schema_version"],
            authority_mode=payload["authority_mode"],
            source_token=payload["source_token"],
            endpoint_id=payload["endpoint_id"],
            market=payload["market"],
            adapter_id=payload["adapter_id"],
            upstream_lineage_id=payload["upstream_lineage_id"],
            authority_ref=payload["authority_ref"],
            capability_surface=payload["capability_surface"],
            evidence_ref=payload["evidence_ref"],
            captured_at=_parse_aware(payload["captured_at"], "authority.captured_at"),
            source_commit_sha=payload["source_commit_sha"],
            source_blob_sha=payload["source_blob_sha"],
            license_spdx=payload["license_spdx"],
            license_ref=payload["license_ref"],
            license_blob_sha=payload["license_blob_sha"],
            digest=payload["digest"],
        )


@dataclass(frozen=True)
class AuthorityDriftDiagnostic:
    status: str
    recorded_authority_digest: str
    current_authority_ref: str | None
    differences: tuple[str, ...]


@dataclass(frozen=True)
class RecordedMarketFixture:
    schema_version: str
    fixture_id: str
    symbol: str
    interval_label: str
    source_query: str
    query_params: Mapping[str, Any]
    capture_provenance_ref: str
    representation: str
    available_at: datetime
    observed_at: datetime
    time_semantics: Mapping[str, Any]
    authority: RecordedAuthoritySnapshot
    rows: tuple[Mapping[str, Any], ...]
    rows_digest: str
    fixture_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != FIXTURE_SCHEMA_VERSION:
            raise ValueError(f"unsupported fixture schema: {self.schema_version}")
        for field_name in (
            "fixture_id",
            "symbol",
            "interval_label",
            "source_query",
            "capture_provenance_ref",
        ):
            _non_empty_trimmed(getattr(self, field_name), field_name)
        if self.representation != REPRESENTATION_NORMALIZED_LICENSED_CSV:
            raise ValueError("unsupported recorded fixture representation")
        if not isinstance(self.query_params, Mapping):
            raise ValueError("query_params must be an object")
        if not isinstance(self.time_semantics, Mapping):
            raise ValueError("time_semantics must be an object")

        object.__setattr__(self, "available_at", _aware_required(self.available_at, "available_at"))
        object.__setattr__(self, "observed_at", _aware_required(self.observed_at, "observed_at"))
        if self.available_at > self.observed_at:
            raise ValueError("available_at cannot be after observed_at")

        # EMBEDDED mode has no independent validity interval. For A3 it therefore
        # must be co-captured with the observation it is meant to authorize.
        if self.authority.captured_at != self.observed_at:
            raise ValueError("embedded authority captured_at must equal observed_at")

        self._validate_representation_metadata()

        object.__setattr__(self, "query_params", deep_freeze(self.query_params))
        object.__setattr__(self, "time_semantics", deep_freeze(self.time_semantics))
        frozen_rows = tuple(deep_freeze(row) for row in self.rows)
        object.__setattr__(self, "rows", frozen_rows)
        self._validate_rows()

        _hex_sha(self.rows_digest, "rows_digest", 64)
        _hex_sha(self.fixture_digest, "fixture_digest", 64)
        if self.rows_digest != stable_hash(self.rows):
            raise ValueError("recorded rows digest mismatch")
        if self.fixture_digest != stable_hash(self.digest_payload()):
            raise ValueError("recorded fixture digest mismatch")

    def _validate_representation_metadata(self) -> None:
        _require_exact_keys(self.query_params, _QUERY_PARAM_KEYS, "query_params")
        _require_exact_keys(self.time_semantics, _TIME_SEMANTIC_KEYS, "time_semantics")

        repository = _canonical_repository(self.query_params["repository"])
        path = _canonical_repo_path(self.query_params["path"], "query_params.path")
        ref = _hex_sha(self.query_params["ref"], "query_params.ref", 40)
        lines, line_start, line_end = _canonical_line_range(
            self.query_params["lines"], "query_params.lines"
        )
        semantic_lines, _, _ = _canonical_line_range(
            self.time_semantics["raw_source_slice_lines"],
            "time_semantics.raw_source_slice_lines",
        )
        if semantic_lines != lines:
            raise ValueError("query lines do not match recorded source-slice lines")

        _non_empty_trimmed(
            self.time_semantics["bar_timestamp_semantic"],
            "time_semantics.bar_timestamp_semantic",
        )
        _non_empty_trimmed(
            self.time_semantics["availability_semantic"],
            "time_semantics.availability_semantic",
        )
        if self.time_semantics["bar_timestamp_semantic"] != BAR_TIMESTAMP_SOURCE_DECLARED:
            raise ValueError("unsupported bar timestamp semantic")
        if (
            self.time_semantics["availability_semantic"]
            != AVAILABILITY_CONSERVATIVE_CAPTURE_SEAL
        ):
            raise ValueError("unsupported availability semantic")
        if self.time_semantics["session_semantics_claimed"] is not False:
            raise ValueError("A3 fixture must not claim session semantics")

        source_commit_time = _parse_aware(
            self.time_semantics["source_commit_time"],
            "time_semantics.source_commit_time",
        )
        if source_commit_time > self.available_at:
            raise ValueError("source_commit_time cannot be after available_at")
        if ref != self.authority.source_commit_sha:
            raise ValueError("query ref must equal pinned authority source commit")

        expected_source_query = _canonical_source_query(
            repository, path, ref, line_start, line_end
        )
        if self.source_query != expected_source_query:
            raise ValueError("source_query does not match canonical source tuple")

        expected_endpoint = f"github.contents:{path}"
        if self.authority.endpoint_id != expected_endpoint:
            raise ValueError("authority endpoint_id does not match query path")

        expected_authority_ref = f"github:{repository}@{ref}:{path}"
        if self.authority.authority_ref != expected_authority_ref:
            raise ValueError("authority_ref does not bind canonical source tuple")
        expected_evidence_ref = f"{repository}:{path}@{ref}"
        if self.authority.evidence_ref != expected_evidence_ref:
            raise ValueError("evidence_ref does not bind canonical source tuple")
        _validate_license_ref(self.authority.license_ref, repository, ref)

        # capture_provenance_ref is descriptive evidence, not a second authority.
        # Still derive it exactly from the structured tuple so a rehashed fixture
        # cannot make the human-readable provenance contradict authoritative data.
        expected_capture_ref = (
            f"GitHub immutable source slice {path} lines {lines} at commit {ref}; "
            f"source repository {self.authority.license_spdx} license preserved"
        )
        if self.capture_provenance_ref != expected_capture_ref:
            raise ValueError("capture_provenance_ref contradicts canonical source tuple")

    def _validate_rows(self) -> None:
        if not self.rows:
            raise ValueError("recorded fixture rows must be non-empty")

        previous_time: datetime | None = None
        for index, row in enumerate(self.rows):
            if not isinstance(row, Mapping):
                raise ValueError(f"row[{index}] must be an object")
            _require_exact_keys(row, _ROW_KEYS, f"row[{index}]")
            event_time = _parse_aware(row["datetime"], f"row[{index}].datetime")
            if event_time > self.available_at:
                raise ValueError("recorded row datetime cannot be after available_at")
            if previous_time is not None and event_time <= previous_time:
                raise ValueError("recorded row datetimes must be strictly increasing and unique")
            previous_time = event_time

            open_px = _decimal_text(row["open"], f"row[{index}].open", allow_zero=False)
            high_px = _decimal_text(row["high"], f"row[{index}].high", allow_zero=False)
            low_px = _decimal_text(row["low"], f"row[{index}].low", allow_zero=False)
            close_px = _decimal_text(row["close"], f"row[{index}].close", allow_zero=False)
            _decimal_text(row["volume"], f"row[{index}].volume", allow_zero=True)

            if high_px < low_px or high_px < open_px or high_px < close_px:
                raise ValueError(f"row[{index}] invalid OHLC envelope")
            if low_px > open_px or low_px > close_px:
                raise ValueError(f"row[{index}] invalid OHLC envelope")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "symbol": self.symbol,
            "interval_label": self.interval_label,
            "source_query": self.source_query,
            "query_params": self.query_params,
            "capture_provenance_ref": self.capture_provenance_ref,
            "representation": self.representation,
            "available_at": self.available_at,
            "observed_at": self.observed_at,
            "time_semantics": self.time_semantics,
            "authority": self.authority.canonical_payload(),
            "rows": self.rows,
            "rows_digest": self.rows_digest,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RecordedMarketFixture":
        if "authority" not in payload:
            raise ValueError("recorded fixture requires capture-time authority")
        _require_exact_keys(payload, _FIXTURE_KEYS, "fixture")
        authority_payload = payload.get("authority")
        rows_payload = payload.get("rows")
        if not isinstance(authority_payload, Mapping):
            raise ValueError("recorded fixture requires capture-time authority")
        if not isinstance(rows_payload, list):
            raise ValueError("recorded fixture rows must be a list")
        return cls(
            schema_version=payload["schema_version"],
            fixture_id=payload["fixture_id"],
            symbol=payload["symbol"],
            interval_label=payload["interval_label"],
            source_query=payload["source_query"],
            query_params=payload["query_params"],
            capture_provenance_ref=payload["capture_provenance_ref"],
            representation=payload["representation"],
            available_at=_parse_aware(payload["available_at"], "available_at"),
            observed_at=_parse_aware(payload["observed_at"], "observed_at"),
            time_semantics=payload["time_semantics"],
            authority=RecordedAuthoritySnapshot.from_mapping(authority_payload),
            rows=tuple(rows_payload),
            rows_digest=payload["rows_digest"],
            fixture_digest=payload["fixture_digest"],
        )

    def historical_authority_resolver(self) -> SourceAuthorityResolver:
        authority = self.authority

        def resolve(
            source_token: str,
            endpoint_id: str,
            market: str,
        ) -> SourceAuthorityResolution | None:
            if (
                source_token != authority.source_token
                or endpoint_id != authority.endpoint_id
                or market != authority.market
            ):
                return None
            return SourceAuthorityResolution(
                source_token=authority.source_token,
                endpoint_id=authority.endpoint_id,
                market=authority.market,
                adapter_id=authority.adapter_id,
                upstream_lineage_id=authority.upstream_lineage_id,
                authority_ref=f"{authority.authority_ref}#sha256:{authority.digest}",
            )

        return resolve

    def materialize_events(self) -> tuple[EventRecord, ...]:
        authority = self.authority
        timestamp_semantic = self.time_semantics["bar_timestamp_semantic"]
        events: list[EventRecord] = []
        for index, row in enumerate(self.rows):
            event_time = _parse_aware(row["datetime"], f"row[{index}].datetime")
            events.append(
                EventRecord(
                    event_id=(
                        f"recorded:{authority.source_token}:{self.symbol}:"
                        f"{self.interval_label}:{event_time.isoformat()}"
                    ),
                    event_type="RECORDED_MARKET_BAR",
                    entity_id=self.symbol,
                    theme_id=None,
                    occurred_at=event_time,
                    event_time=event_time,
                    published_at=None,
                    available_at=self.available_at,
                    observed_at=self.observed_at,
                    created_at=self.observed_at,
                    source_id=self.source_query,
                    payload={
                        "fixture_id": self.fixture_id,
                        "recorded_authority_digest": authority.digest,
                        "bar_timestamp_semantic": timestamp_semantic,
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["volume"],
                    },
                    trace_id=f"trace:recorded-fixture:{self.fixture_id}",
                    source_kind="PROVIDER",
                    source_token=authority.source_token,
                    endpoint_id=authority.endpoint_id,
                    market=authority.market,
                )
            )
        return tuple(events)


def validate_historical_authority_binding(
    authority: RecordedAuthoritySnapshot,
    resolver: SourceAuthorityResolver,
) -> SourceAuthorityResolution:
    resolution = resolver(authority.source_token, authority.endpoint_id, authority.market)
    expected_ref = f"{authority.authority_ref}#sha256:{authority.digest}"
    if resolution is None:
        raise ValueError("historical authority resolver cannot resolve capture-time binding")
    if (
        resolution.source_token != authority.source_token
        or resolution.endpoint_id != authority.endpoint_id
        or resolution.market != authority.market
        or resolution.adapter_id != authority.adapter_id
        or resolution.upstream_lineage_id != authority.upstream_lineage_id
        or resolution.authority_ref != expected_ref
    ):
        raise ValueError("resolver does not prove capture-time authority")
    return resolution


@dataclass(frozen=True)
class RecordedFixtureReplay:
    replay_result: ReplayResult
    fixture_digest: str
    authority_digest: str
    authority_drift: AuthorityDriftDiagnostic


def diagnose_current_authority(
    authority: RecordedAuthoritySnapshot,
    current_resolver: SourceAuthorityResolver | None,
) -> AuthorityDriftDiagnostic:
    if current_resolver is None:
        return AuthorityDriftDiagnostic(
            status=AUTHORITY_DRIFT_NOT_CHECKED,
            recorded_authority_digest=authority.digest,
            current_authority_ref=None,
            differences=(),
        )

    current = current_resolver(authority.source_token, authority.endpoint_id, authority.market)
    if current is None:
        return AuthorityDriftDiagnostic(
            status=AUTHORITY_DRIFT_MISSING,
            recorded_authority_digest=authority.digest,
            current_authority_ref=None,
            differences=("current_authority_missing",),
        )

    differences = tuple(
        name
        for name, recorded, live in (
            ("source_token", authority.source_token, current.source_token),
            ("endpoint_id", authority.endpoint_id, current.endpoint_id),
            ("market", authority.market, current.market),
            ("adapter_id", authority.adapter_id, current.adapter_id),
            ("upstream_lineage_id", authority.upstream_lineage_id, current.upstream_lineage_id),
        )
        if recorded != live
    )
    return AuthorityDriftDiagnostic(
        status=AUTHORITY_DRIFT_DETECTED if differences else AUTHORITY_DRIFT_MATCH,
        recorded_authority_digest=authority.digest,
        current_authority_ref=current.authority_ref,
        differences=differences,
    )


def replay_recorded_fixture(
    fixture: RecordedMarketFixture,
    decision_clock: datetime,
    *,
    current_authority_resolver: SourceAuthorityResolver | None = None,
    rule_version: str = "run-b-a3-v0.1",
) -> RecordedFixtureReplay:
    historical_resolver = fixture.historical_authority_resolver()
    validate_historical_authority_binding(fixture.authority, historical_resolver)
    result = replay(
        fixture.materialize_events(),
        decision_clock,
        rule_version=rule_version,
        source_authority_resolver=historical_resolver,
    )
    return RecordedFixtureReplay(
        replay_result=result,
        fixture_digest=fixture.fixture_digest,
        authority_digest=fixture.authority.digest,
        authority_drift=diagnose_current_authority(
            fixture.authority,
            current_authority_resolver,
        ),
    )


def load_recorded_fixture(path: str | Path) -> RecordedMarketFixture:
    payload = load_strict_json(path, "recorded fixture")
    if not isinstance(payload, Mapping):
        raise ValueError("recorded fixture root must be an object")
    return RecordedMarketFixture.from_mapping(payload)
