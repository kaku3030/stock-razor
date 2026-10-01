"""Strategy Lab V0.1 -- Replay Evidence Manifest Differential Foundation.

Provides an immutable, content-addressed manifest for one piece of captured
replay evidence (a fixture / capture used to reproduce an experiment run),
plus a pure differential comparison between two such manifests. It answers
"did the governed identity of this captured evidence change, and exactly
which field caused that", never "was the strategy profitable" and never
"replay this evidence".

Pure compute, stdlib plus the one closed contract it consumes
(``temporal_contract`` for aware-datetime canonicalization). It does not
touch SQLAlchemy, the repository layer, the database, a trading calendar, a
live data provider, or any execution/broker path.

Scope boundary -- read this before wiring this module into anything
--------------------------------------------------------------------
This module is deliberately **not**:

- a second replay engine -- it holds and compares declared facts about
  evidence; it never fetches, re-runs, or reproduces anything itself.
- a second experiment authority -- ``experiment_id`` here is a plain foreign
  reference into the existing Experiment Registry
  (``experiment_governance.ExperimentManifest.experiment_id``). This module
  does not re-implement lineage, parent/root invariants, or identity
  conflict resolution; those remain exclusively owned by
  ``experiment_governance``.
- a provider runtime or a Currentness runtime -- ``provider`` /
  ``provider_endpoint`` / ``calendar_source`` are opaque, caller-supplied
  strings recorded for provenance. This module does not call a provider,
  does not know what "current" means, and does not resolve a trading
  calendar.
- a Shadow/CORE/LIVE path or a broker/order path -- there is no execution
  surface here at all, sandboxed or otherwise.
- a replacement for the OOS Consumption Ledger's own idempotent-replay
  semantics (``oos_consumption.OOSClaimStatus.IDEMPOTENT_REPLAY`` /
  ``OOSBurnStatus.IDEMPOTENT_REPLAY``). "Replay" in this module's name means
  *evidence-capture replay for reproducibility*; it is a distinct concept
  from the ledger's operation-idempotency replay, and this module never
  reads or writes ledger state. Existing Strategy Lab replay/OOS semantics
  remain authoritative and unmodified by this module.

Trust boundary (V0.1 -- read this before relying on ``manifest_hash``)
------------------------------------------------------------------------
Exactly as documented in ``experiment_governance``: ``raw_evidence_digest``,
``fixture_hash``, and every other governed field are **caller-supplied
trusted inputs**. ``manifest_hash`` proves the manifest is a consistent,
canonical function of the fields it was handed; it does not prove those
fields faithfully describe the external evidence they claim to describe.

UNKNOWN stays UNKNOWN
----------------------
Every provenance field below ``experiment_id`` / ``fixture_id`` /
``capture_id`` / ``schema_version`` is optional, and ``None`` means "this
fact is not known", not "this fact is empty" or "this fact is zero". A
missing value is never coerced, defaulted, or silently upgraded to a
confident value, and ``None`` is a legitimate, permanent, hashable terminal
state: filling in a previously-unknown field is itself a governed-identity
change (see below), never a free correction.

The three time fields (``event_time``, ``publication_time``, ``observed_at``)
follow this same rule through ``EvidenceTimeEnvelope``: each carries its own
``*_quality`` marker, and a marker of ``TimeQuality.UNKNOWN`` is required
exactly when its value is ``None`` and forbidden otherwise, so a caller can
never claim ``EXACT`` confidence about a fact it does not have, nor leave a
present value's confidence unstated.

``event_time`` / ``publication_time`` / ``observed_at`` are never derived
from one another. This is enforced **structurally**: ``EvidenceTimeEnvelope``
has no cross-field default and no fallback branch that reads one of these
three to fill in another, so there is no code path by which this module
could derive a missing instant. This module deliberately does **not**
additionally reject the three fields being numerically equal to one
another: a provider that stamps ``observed_at`` at the same instant it
stamps ``publication_time`` (an instantaneous capture) is a legitimate,
literal fact about that evidence, not a derivation performed by this code.
Treating that coincidence as a hard error would make real captures
unrepresentable for no safety gain; the anti-derivation guarantee that
matters is structural, not a numeric-inequality check on caller data.

Derived output is never the same object as original evidence
--------------------------------------------------------------
``require_derived_output_distinct`` is a standalone guard for callers that
persist an artifact derived from the evidence this manifest describes
(a computed feature, a rendered report, a re-encoded copy, ...): it rejects
a derived-output reference that is identity-equal to the raw-evidence
reference, so a derived artifact can never silently masquerade as the
original evidence it came from.

Canonicalization is narrow on purpose
--------------------------------------
The canonical manifest payload is an explicit, hand-enumerated dict of
every governed field (see ``_canonical_payload``). This is not a general
JSON canonicalization framework: the payload is built field-by-field with
constrained hashable types (``str | None``, enum ``.value``, canonical UTC
datetime text), so nothing can be silently swept into or out of the hash by
changing the dataclass's ``__dict__``. ``manifest_hash`` itself is a derived
read-only property; there is no hash field to inject or assign, so a caller
can neither forge it nor mutate what it computes to. ``created_at`` is
excluded structurally, exactly as ``experiment_governance.ExperimentManifest``
excludes it: it is bookkeeping about when this manifest object was built,
not an identity fact about the evidence it describes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .temporal_contract import canonical_utc_datetime, canonical_utc_text

_MANIFEST_SCHEMA = "replay-evidence-manifest-differential-v0.1"


def _require_nonempty_str(label: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string, got {value!r}")
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value


def _require_optional_str(label: str, value: Any) -> str | None:
    """``None`` means UNKNOWN; anything else must be a non-empty string."""

    if value is None:
        return None
    return _require_nonempty_str(label, value)


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class TimeQuality(str, Enum):
    """Confidence marker for one instant in ``EvidenceTimeEnvelope``.

    ``UNKNOWN`` is required exactly when the paired value is ``None`` and
    forbidden exactly when the paired value is present -- see the module
    docstring's "UNKNOWN stays UNKNOWN" section. There is deliberately no
    default: a caller must state a quality for every instant it supplies.
    """

    UNKNOWN = "unknown"
    EXACT = "exact"
    APPROXIMATE = "approximate"


def _require_time_quality(label: str, value: Any) -> TimeQuality:
    if not isinstance(value, TimeQuality):
        raise ValueError(f"{label} must be a TimeQuality instance, got {value!r}")
    return value


def _require_optional_datetime(label: str, value: Any) -> datetime | None:
    if value is None:
        return None
    return canonical_utc_datetime(value)


@dataclass(frozen=True)
class EvidenceTimeEnvelope:
    """Three independently-optional instants for one piece of evidence.

    ``event_time`` (when the underlying fact occurred), ``publication_time``
    (when the source published it), and ``observed_at`` (when this system
    captured it) are three distinct concepts that are never derived from one
    another -- see the module docstring. Each carries its own
    ``TimeQuality`` marker; ``None`` + ``TimeQuality.UNKNOWN`` is the only
    legal pairing for a missing instant, and a present instant must carry a
    non-``UNKNOWN`` quality.
    """

    event_time: datetime | None
    event_time_quality: TimeQuality
    publication_time: datetime | None
    publication_time_quality: TimeQuality
    observed_at: datetime | None
    observed_at_quality: TimeQuality

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_time", _require_optional_datetime("event_time", self.event_time)
        )
        object.__setattr__(
            self,
            "publication_time",
            _require_optional_datetime("publication_time", self.publication_time),
        )
        object.__setattr__(
            self, "observed_at", _require_optional_datetime("observed_at", self.observed_at)
        )

        object.__setattr__(
            self,
            "event_time_quality",
            _require_time_quality("event_time_quality", self.event_time_quality),
        )
        object.__setattr__(
            self,
            "publication_time_quality",
            _require_time_quality("publication_time_quality", self.publication_time_quality),
        )
        object.__setattr__(
            self,
            "observed_at_quality",
            _require_time_quality("observed_at_quality", self.observed_at_quality),
        )

        for value, quality, label in (
            (self.event_time, self.event_time_quality, "event_time"),
            (self.publication_time, self.publication_time_quality, "publication_time"),
            (self.observed_at, self.observed_at_quality, "observed_at"),
        ):
            if value is None and quality is not TimeQuality.UNKNOWN:
                raise ValueError(
                    f"{label} is None (UNKNOWN) but {label}_quality is {quality.value!r}; "
                    "a missing instant must carry TimeQuality.UNKNOWN"
                )
            if value is not None and quality is TimeQuality.UNKNOWN:
                raise ValueError(
                    f"{label} is present but {label}_quality is UNKNOWN; a present instant "
                    "must state a non-UNKNOWN quality"
                )

    def as_canonical_payload(self) -> dict[str, Any]:
        """Explicit, hand-enumerated payload used by ``ReplayEvidenceManifest``.

        ``None`` is encoded as JSON ``null`` -- a distinguishable, hashable
        value in its own right, so filling in a previously-unknown instant
        changes the payload (and therefore ``manifest_hash``) exactly as any
        other governed-field change would.
        """

        return {
            "event_time": canonical_utc_text(self.event_time) if self.event_time else None,
            "event_time_quality": self.event_time_quality.value,
            "publication_time": (
                canonical_utc_text(self.publication_time) if self.publication_time else None
            ),
            "publication_time_quality": self.publication_time_quality.value,
            "observed_at": canonical_utc_text(self.observed_at) if self.observed_at else None,
            "observed_at_quality": self.observed_at_quality.value,
        }


# Every field name in this payload is a governed identity field: changing
# any one of them must change manifest_hash. Listed here once so the
# manifest's canonical payload builder and the differential's field-by-field
# comparison stay in lockstep with each other and cannot silently drift.
GOVERNED_FIELD_NAMES: tuple[str, ...] = (
    "experiment_id",
    "fixture_id",
    "capture_id",
    "event_time",
    "event_time_quality",
    "publication_time",
    "publication_time_quality",
    "observed_at",
    "observed_at_quality",
    "provider",
    "provider_endpoint",
    "source_record_id",
    "model_id",
    "model_version",
    "prompt_version",
    "tool_schema_version",
    "rule_version",
    "seed",
    "raw_evidence_ref",
    "raw_evidence_digest",
    "fixture_hash",
    "timezone",
    "calendar_source",
    "provenance_parent",
    "license_class",
    "redistribution_class",
)


@dataclass(frozen=True)
class ReplayEvidenceManifest:
    """Immutable, content-addressed identity for one captured replay fixture.

    ``experiment_id`` is a foreign reference into the existing Experiment
    Registry (``experiment_governance.ExperimentManifest``); this dataclass
    does not validate, own, or audit that reference -- see the module
    docstring's scope boundary.
    """

    # Hard identifiers -- required, never UNKNOWN.
    experiment_id: str
    fixture_id: str
    capture_id: str
    created_at: datetime

    # Time envelope -- see EvidenceTimeEnvelope.
    time_envelope: EvidenceTimeEnvelope

    # Provenance -- optional; None means UNKNOWN.
    provider: str | None = None
    provider_endpoint: str | None = None
    source_record_id: str | None = None

    # Computation identity -- optional; None means UNKNOWN.
    model_id: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    tool_schema_version: str | None = None
    rule_version: str | None = None
    seed: str | None = None

    # Evidence integrity -- optional; None means UNKNOWN.
    raw_evidence_ref: str | None = None
    raw_evidence_digest: str | None = None
    fixture_hash: str | None = None

    # Context / legal -- optional; None means UNKNOWN.
    timezone: str | None = None
    calendar_source: str | None = None
    provenance_parent: str | None = None
    license_class: str | None = None
    redistribution_class: str | None = None

    schema_version: str = _MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "experiment_id", _require_nonempty_str("experiment_id", self.experiment_id)
        )
        object.__setattr__(
            self, "fixture_id", _require_nonempty_str("fixture_id", self.fixture_id)
        )
        object.__setattr__(
            self, "capture_id", _require_nonempty_str("capture_id", self.capture_id)
        )
        object.__setattr__(
            self, "schema_version", _require_nonempty_str("schema_version", self.schema_version)
        )
        object.__setattr__(self, "created_at", canonical_utc_datetime(self.created_at))

        if not isinstance(self.time_envelope, EvidenceTimeEnvelope):
            raise ValueError(
                f"time_envelope must be an EvidenceTimeEnvelope, got {self.time_envelope!r}"
            )

        for label in (
            "provider",
            "provider_endpoint",
            "source_record_id",
            "model_id",
            "model_version",
            "prompt_version",
            "tool_schema_version",
            "rule_version",
            "seed",
            "raw_evidence_ref",
            "raw_evidence_digest",
            "fixture_hash",
            "timezone",
            "calendar_source",
            "provenance_parent",
            "license_class",
            "redistribution_class",
        ):
            object.__setattr__(self, label, _require_optional_str(label, getattr(self, label)))

    def _canonical_payload(self) -> dict[str, Any]:
        """Explicit governed-field payload -- see ``GOVERNED_FIELD_NAMES``.

        Hand-enumerated rather than derived from ``__dict__`` so that
        ``created_at`` (bookkeeping, not identity) and ``manifest_hash``
        (a derived property, never a stored field) are excluded
        structurally: they are never passed to the canonicalizer, not
        stripped out of it.
        """

        payload: dict[str, Any] = {
            "experiment_id": self.experiment_id,
            "fixture_id": self.fixture_id,
            "capture_id": self.capture_id,
            "provider": self.provider,
            "provider_endpoint": self.provider_endpoint,
            "source_record_id": self.source_record_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "tool_schema_version": self.tool_schema_version,
            "rule_version": self.rule_version,
            "seed": self.seed,
            "raw_evidence_ref": self.raw_evidence_ref,
            "raw_evidence_digest": self.raw_evidence_digest,
            "fixture_hash": self.fixture_hash,
            "timezone": self.timezone,
            "calendar_source": self.calendar_source,
            "provenance_parent": self.provenance_parent,
            "license_class": self.license_class,
            "redistribution_class": self.redistribution_class,
        }
        payload.update(self.time_envelope.as_canonical_payload())
        assert set(payload) == set(GOVERNED_FIELD_NAMES), (
            "canonical payload keys drifted from GOVERNED_FIELD_NAMES"
        )
        return payload

    @property
    def manifest_hash(self) -> str:
        """SHA256(canonical(schema_version + every governed field)).

        ``experiment_id`` participates in the hash as ordinary governed
        content here (unlike ``experiment_governance.ExperimentManifest``,
        where it is structurally excluded as the lineage key): this
        manifest names one evidence capture, not an experiment lineage
        node, so there is no separate lineage identity for it to be
        excluded in favor of.
        """

        payload = {"schema": self.schema_version, **self._canonical_payload()}
        return _sha256(_canonical_json(payload))

    def governed_field(self, name: str) -> Any:
        """Read one governed field's raw (pre-JSON-encoding) value by name."""

        if name not in GOVERNED_FIELD_NAMES:
            raise ValueError(f"{name!r} is not a governed field of ReplayEvidenceManifest")
        if hasattr(self.time_envelope, name):
            return getattr(self.time_envelope, name)
        return getattr(self, name)


@dataclass(frozen=True)
class ReplayManifestFieldDiff:
    field: str
    changed: bool
    before: Any
    after: Any


@dataclass(frozen=True)
class ReplayManifestDifferential:
    """Field-by-field comparison between two ``ReplayEvidenceManifest``.

    ``identity_changed`` is derived from ``manifest_hash`` equality, which is
    itself a pure function of exactly the fields compared in ``field_diffs``
    -- so ``identity_changed`` and "at least one field_diff has changed=True"
    can never disagree by construction, not by an extra runtime check.
    """

    before_manifest_hash: str
    after_manifest_hash: str
    identity_changed: bool
    field_diffs: tuple[ReplayManifestFieldDiff, ...]
    changed_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "changed_fields",
            tuple(sorted(diff.field for diff in self.field_diffs if diff.changed)),
        )


def diff_replay_manifests(
    before: ReplayEvidenceManifest, after: ReplayEvidenceManifest
) -> ReplayManifestDifferential:
    """Pure, order-independent differential over every governed field.

    Does not compare ``created_at`` (bookkeeping, excluded from identity) or
    ``schema_version`` mismatches beyond what already flows into
    ``manifest_hash``; those wishing to detect a schema migration should
    compare ``schema_version`` directly.
    """

    if not isinstance(before, ReplayEvidenceManifest):
        raise ValueError(f"before must be a ReplayEvidenceManifest, got {before!r}")
    if not isinstance(after, ReplayEvidenceManifest):
        raise ValueError(f"after must be a ReplayEvidenceManifest, got {after!r}")

    diffs = []
    for name in GOVERNED_FIELD_NAMES:
        before_value = before.governed_field(name)
        after_value = after.governed_field(name)
        diffs.append(
            ReplayManifestFieldDiff(
                field=name,
                changed=before_value != after_value,
                before=before_value,
                after=after_value,
            )
        )

    return ReplayManifestDifferential(
        before_manifest_hash=before.manifest_hash,
        after_manifest_hash=after.manifest_hash,
        identity_changed=before.manifest_hash != after.manifest_hash,
        field_diffs=tuple(diffs),
        changed_fields=(),  # recomputed in __post_init__
    )


@dataclass(frozen=True)
class ReplayDeterminismCheck:
    """Result of comparing two claimed replay outputs against their manifests."""

    consistent: bool
    reason: str | None

    def __post_init__(self) -> None:
        if not self.consistent and not self.reason:
            raise ValueError("an inconsistent check must state a reason")
        if self.consistent and self.reason is not None:
            raise ValueError("a consistent check must not carry a reason")


def check_replay_determinism(
    *,
    manifest_a: ReplayEvidenceManifest,
    output_digest_a: str,
    manifest_b: ReplayEvidenceManifest,
    output_digest_b: str,
) -> ReplayDeterminismCheck:
    """Verify: same governed manifest identity -> same declared output digest.

    This is a pure comparison of caller-supplied facts, not a second replay
    engine: it never executes, fetches, or reproduces anything, and it takes
    no position on manifests with *different* identities (they carry no
    determinism obligation to each other and are always ``consistent``).
    Only when ``manifest_a.manifest_hash == manifest_b.manifest_hash`` does a
    mismatched ``output_digest`` become a reportable violation.
    """

    _require_nonempty_str("output_digest_a", output_digest_a)
    _require_nonempty_str("output_digest_b", output_digest_b)
    if manifest_a.manifest_hash != manifest_b.manifest_hash:
        return ReplayDeterminismCheck(consistent=True, reason=None)
    if output_digest_a != output_digest_b:
        return ReplayDeterminismCheck(
            consistent=False,
            reason=(
                f"manifest_hash {manifest_a.manifest_hash!r} is identical but output digests "
                f"differ ({output_digest_a!r} != {output_digest_b!r})"
            ),
        )
    return ReplayDeterminismCheck(consistent=True, reason=None)


def require_derived_output_distinct(raw_evidence_ref: str, derived_output_ref: str) -> None:
    """Reject a derived output that claims to be its own original evidence.

    A derived artifact (a computed feature, a rendered report, a re-encoded
    copy, ...) must never be identity-equal to the raw evidence reference it
    was derived from. This is a standalone guard for callers that persist
    such artifacts alongside a ``ReplayEvidenceManifest``; it is not itself a
    manifest field because "derived output" is caller-owned storage, not
    part of the minimum evidence-identity schema.
    """

    _require_nonempty_str("raw_evidence_ref", raw_evidence_ref)
    _require_nonempty_str("derived_output_ref", derived_output_ref)
    if raw_evidence_ref == derived_output_ref:
        raise ValueError(
            "derived_output_ref must not equal raw_evidence_ref: a derived output cannot be "
            f"identity-equal to the original evidence it was derived from ({raw_evidence_ref!r})"
        )
