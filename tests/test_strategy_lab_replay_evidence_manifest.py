from datetime import datetime, timezone

import pytest

from src.services.strategy_lab.replay_evidence_manifest import (
    GOVERNED_FIELD_NAMES,
    EvidenceTimeEnvelope,
    ReplayDeterminismCheck,
    ReplayEvidenceManifest,
    TimeQuality,
    check_replay_determinism,
    diff_replay_manifests,
    require_derived_output_distinct,
)

UTC = timezone.utc

# Permanent adversarial test IDs for this module -- anti-shrink protected,
# matching the convention in tests/test_strategy_lab_experiment_governance.py
# and tests/test_strategy_lab_adversarial.py.
PERMANENT_REPLAY_MANIFEST_ADVERSARIAL_TEST_IDS = (
    "TEST_UNKNOWN_TIME_REQUIRES_UNKNOWN_QUALITY",
    "TEST_PRESENT_TIME_REJECTS_UNKNOWN_QUALITY",
    "TEST_MISSING_TIME_STAYS_NONE_NOT_COERCED",
    "TEST_CREATED_AT_EXCLUDED_FROM_HASH",
    "TEST_EACH_GOVERNED_FIELD_CHANGE_CHANGES_HASH",
    "TEST_FILLING_IN_UNKNOWN_FIELD_CHANGES_HASH",
    "TEST_IDENTICAL_MANIFEST_STABLE_HASH",
    "TEST_DIFFERENTIAL_REPORTS_EXACT_CHANGED_FIELDS",
    "TEST_DETERMINISM_CHECK_SAME_MANIFEST_SAME_OUTPUT",
    "TEST_DETERMINISM_CHECK_SAME_MANIFEST_DIFFERENT_OUTPUT_VIOLATION",
    "TEST_DETERMINISM_CHECK_DIFFERENT_MANIFEST_NO_OBLIGATION",
    "TEST_DERIVED_OUTPUT_CANNOT_EQUAL_RAW_EVIDENCE",
    "TEST_NAIVE_DATETIME_REJECTED",
)


def _dt(day: int = 10, hour: int = 12) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _envelope(**overrides) -> EvidenceTimeEnvelope:
    base = dict(
        event_time=_dt(day=1),
        event_time_quality=TimeQuality.EXACT,
        publication_time=_dt(day=2),
        publication_time_quality=TimeQuality.EXACT,
        observed_at=_dt(day=3),
        observed_at_quality=TimeQuality.APPROXIMATE,
    )
    base.update(overrides)
    return EvidenceTimeEnvelope(**base)


def _manifest(**overrides) -> ReplayEvidenceManifest:
    base = dict(
        experiment_id="exp-1",
        fixture_id="fix-1",
        capture_id="cap-1",
        created_at=_dt(day=10),
        time_envelope=_envelope(),
        provider="fmp",
        provider_endpoint="/v3/quote",
        source_record_id="rec-1",
        model_id="claude-sonnet-5",
        model_version="2026-01",
        prompt_version="p-1",
        tool_schema_version="t-1",
        rule_version="r-1",
        seed="42",
        raw_evidence_ref="s3://bucket/raw/1",
        raw_evidence_digest="digest-raw-1",
        fixture_hash="hash-fixture-1",
        timezone="UTC",
        calendar_source="XNYS",
        provenance_parent=None,
        license_class="internal",
        redistribution_class="no_redistribution",
    )
    base.update(overrides)
    return ReplayEvidenceManifest(**base)


# ---- EvidenceTimeEnvelope: UNKNOWN preservation ----


def test_unknown_time_requires_unknown_quality() -> None:
    envelope = EvidenceTimeEnvelope(
        event_time=None,
        event_time_quality=TimeQuality.UNKNOWN,
        publication_time=None,
        publication_time_quality=TimeQuality.UNKNOWN,
        observed_at=None,
        observed_at_quality=TimeQuality.UNKNOWN,
    )
    assert envelope.event_time is None
    assert envelope.event_time_quality is TimeQuality.UNKNOWN


def test_missing_time_with_non_unknown_quality_rejected() -> None:
    with pytest.raises(ValueError, match="UNKNOWN"):
        EvidenceTimeEnvelope(
            event_time=None,
            event_time_quality=TimeQuality.EXACT,
            publication_time=_dt(),
            publication_time_quality=TimeQuality.EXACT,
            observed_at=_dt(),
            observed_at_quality=TimeQuality.EXACT,
        )


def test_present_time_rejects_unknown_quality() -> None:
    with pytest.raises(ValueError, match="UNKNOWN"):
        EvidenceTimeEnvelope(
            event_time=_dt(),
            event_time_quality=TimeQuality.UNKNOWN,
            publication_time=_dt(),
            publication_time_quality=TimeQuality.EXACT,
            observed_at=_dt(),
            observed_at_quality=TimeQuality.EXACT,
        )


def test_missing_time_stays_none_not_coerced() -> None:
    envelope = _envelope(publication_time=None, publication_time_quality=TimeQuality.UNKNOWN)
    payload = envelope.as_canonical_payload()
    assert payload["publication_time"] is None
    assert payload["publication_time_quality"] == "unknown"


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        EvidenceTimeEnvelope(
            event_time=datetime(2026, 1, 1),
            event_time_quality=TimeQuality.EXACT,
            publication_time=None,
            publication_time_quality=TimeQuality.UNKNOWN,
            observed_at=None,
            observed_at_quality=TimeQuality.UNKNOWN,
        )


def test_event_publication_observed_are_independent_fields() -> None:
    """No field is derived from another -- all three may legitimately coincide."""

    same_instant = _dt(day=5)
    envelope = EvidenceTimeEnvelope(
        event_time=same_instant,
        event_time_quality=TimeQuality.EXACT,
        publication_time=same_instant,
        publication_time_quality=TimeQuality.EXACT,
        observed_at=same_instant,
        observed_at_quality=TimeQuality.EXACT,
    )
    assert envelope.event_time == envelope.publication_time == envelope.observed_at


# ---- manifest_hash contract ----


def test_created_at_excluded_from_hash() -> None:
    base = _manifest()
    retimed = _manifest(created_at=_dt(day=28, hour=3))
    assert base.manifest_hash == retimed.manifest_hash


def test_identical_manifest_stable_hash() -> None:
    assert _manifest().manifest_hash == _manifest().manifest_hash


@pytest.mark.parametrize(
    "field,override",
    [
        ("experiment_id", {"experiment_id": "exp-2"}),
        ("fixture_id", {"fixture_id": "fix-2"}),
        ("capture_id", {"capture_id": "cap-2"}),
        ("provider", {"provider": "finnhub"}),
        ("provider_endpoint", {"provider_endpoint": "/other"}),
        ("source_record_id", {"source_record_id": "rec-2"}),
        ("model_id", {"model_id": "other-model"}),
        ("model_version", {"model_version": "2026-02"}),
        ("prompt_version", {"prompt_version": "p-2"}),
        ("tool_schema_version", {"tool_schema_version": "t-2"}),
        ("rule_version", {"rule_version": "r-2"}),
        ("seed", {"seed": "43"}),
        ("raw_evidence_ref", {"raw_evidence_ref": "s3://bucket/raw/2"}),
        ("raw_evidence_digest", {"raw_evidence_digest": "digest-raw-2"}),
        ("fixture_hash", {"fixture_hash": "hash-fixture-2"}),
        ("timezone", {"timezone": "America/New_York"}),
        ("calendar_source", {"calendar_source": "XHKG"}),
        ("provenance_parent", {"provenance_parent": "cap-0"}),
        ("license_class", {"license_class": "public"}),
        ("redistribution_class", {"redistribution_class": "redistribution_ok"}),
    ],
)
def test_each_governed_field_change_changes_hash(field: str, override: dict) -> None:
    base = _manifest()
    mutated = _manifest(**override)
    assert base.manifest_hash != mutated.manifest_hash, f"{field} did not affect manifest_hash"


def test_time_envelope_field_change_changes_hash() -> None:
    base = _manifest()
    mutated = _manifest(time_envelope=_envelope(observed_at=_dt(day=9)))
    assert base.manifest_hash != mutated.manifest_hash


def test_filling_in_unknown_field_changes_hash() -> None:
    unknown = _manifest(seed=None)
    known = _manifest(seed="42")
    assert unknown.manifest_hash != known.manifest_hash


def test_governed_field_names_cover_every_hashed_field() -> None:
    manifest = _manifest()
    payload = manifest._canonical_payload()
    assert set(payload) == set(GOVERNED_FIELD_NAMES)


# ---- differential ----


def test_differential_reports_exact_changed_fields() -> None:
    before = _manifest()
    after = _manifest(provider="finnhub", seed="43")
    differential = diff_replay_manifests(before, after)
    assert differential.identity_changed is True
    assert differential.changed_fields == ("provider", "seed")
    for diff in differential.field_diffs:
        if diff.field in ("provider", "seed"):
            assert diff.changed is True
        else:
            assert diff.changed is False


def test_differential_no_change_no_identity_change() -> None:
    differential = diff_replay_manifests(_manifest(), _manifest())
    assert differential.identity_changed is False
    assert differential.changed_fields == ()
    assert differential.before_manifest_hash == differential.after_manifest_hash


# ---- determinism check ----


def test_determinism_check_same_manifest_same_output() -> None:
    manifest = _manifest()
    result = check_replay_determinism(
        manifest_a=manifest,
        output_digest_a="out-1",
        manifest_b=_manifest(),
        output_digest_b="out-1",
    )
    assert result == ReplayDeterminismCheck(consistent=True, reason=None)


def test_determinism_check_same_manifest_different_output_is_violation() -> None:
    result = check_replay_determinism(
        manifest_a=_manifest(),
        output_digest_a="out-1",
        manifest_b=_manifest(),
        output_digest_b="out-2",
    )
    assert result.consistent is False
    assert "out-1" in result.reason and "out-2" in result.reason


def test_determinism_check_different_manifest_carries_no_obligation() -> None:
    result = check_replay_determinism(
        manifest_a=_manifest(),
        output_digest_a="out-1",
        manifest_b=_manifest(seed="different"),
        output_digest_b="out-2",
    )
    assert result.consistent is True


# ---- derived output distinctness ----


def test_derived_output_cannot_equal_raw_evidence() -> None:
    with pytest.raises(ValueError, match="identity-equal"):
        require_derived_output_distinct("s3://bucket/raw/1", "s3://bucket/raw/1")


def test_derived_output_distinct_from_raw_evidence_is_fine() -> None:
    require_derived_output_distinct("s3://bucket/raw/1", "s3://bucket/derived/1")
