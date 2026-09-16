from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from src.services.strategy_lab.recorded_fixture import (
    AUTHORITY_DRIFT_DETECTED,
    AUTHORITY_DRIFT_MATCH,
    AUTHORITY_DRIFT_MISSING,
    RecordedMarketFixture,
    diagnose_current_authority,
    load_recorded_fixture,
    replay_recorded_fixture,
    validate_historical_authority_binding,
)
from src.services.strategy_lab.replay_baseline import ReplayBaselineEngine
from src.services.strategy_lab.replay_contract import (
    EventRecord,
    InMemoryEventStore,
    SourceAuthorityResolution,
    stable_hash,
)

UTC = timezone.utc
FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "strategy_lab"
    / "aapl_getdata_12h_recorded_fixture_v1.json"
)
DECISION = datetime(2026, 9, 10, 9, 35, 34, tzinfo=UTC)
BEFORE_CAPTURE = datetime(2026, 9, 10, 9, 35, 32, tzinfo=UTC)
AUTHORITY_DIGEST = "815f73e069da4a4c3a99dd09af3a75f6fd666a1dd10b5290e872ee6723f4c937"
ROWS_DIGEST = "767111a5c9321aa1c3b6a127d1e25c445ae8f670ca76583d412d9b43ea65dfd4"
FIXTURE_DIGEST = "e7257f91405a0122fdd1da2cb628350c9b0bcbf203aa655cea96b9abfa9654e1"


def raw_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _rehash_authority(payload):
    authority = payload["authority"]
    authority["digest"] = stable_hash({key: value for key, value in authority.items() if key != "digest"})


def _rehash_fixture(payload):
    payload["rows_digest"] = stable_hash(payload["rows"])
    payload["fixture_digest"] = stable_hash(
        {key: value for key, value in payload.items() if key != "fixture_digest"}
    )


def _rehash_all(payload):
    _rehash_authority(payload)
    _rehash_fixture(payload)


def current_match(source_token, endpoint_id, market):
    return SourceAuthorityResolution(
        source_token=source_token,
        endpoint_id=endpoint_id,
        market=market,
        adapter_id="github_content",
        upstream_lineage_id="getdata_finance",
        authority_ref="current:getdata-finance",
    )


def current_drift(source_token, endpoint_id, market):
    return SourceAuthorityResolution(
        source_token=source_token,
        endpoint_id=endpoint_id,
        market=market,
        adapter_id="future_adapter",
        upstream_lineage_id="future_upstream",
        authority_ref="current:changed-provider-authority",
    )


def current_missing(source_token, endpoint_id, market):
    return None


def test_licensed_recorded_fixture_loads_with_immutable_source_version():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    assert fixture.fixture_digest == FIXTURE_DIGEST
    assert fixture.rows_digest == ROWS_DIGEST
    assert fixture.authority.digest == AUTHORITY_DIGEST
    assert fixture.authority.source_commit_sha == "e9cebf45a7b68ca87e537c1f2d7f7ea312e79a1b"
    assert fixture.authority.source_blob_sha == "a1d9e2cbced456e2a15f091a389f7382e4f236ec"
    assert fixture.authority.license_spdx == "MIT"
    assert fixture.authority.license_blob_sha == "bfeadbe2ed775c9afbba1b2a19f4e5301e5acf33"
    assert len(fixture.rows) == 8
    assert fixture.rows[0]["datetime"] == "2026-05-13T12:00:00+00:00"
    assert fixture.rows[-1]["close"] == "309.83999999999986"


def test_recorded_fixture_replay_uses_capture_time_authority_even_after_current_drift():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    result = replay_recorded_fixture(fixture, DECISION, current_authority_resolver=current_drift)
    assert len(result.replay_result.snapshot.accepted_event_ids) == 8
    assert result.authority_drift.status == AUTHORITY_DRIFT_DETECTED
    assert result.authority_drift.differences == ("adapter_id", "upstream_lineage_id")
    assert result.replay_result.snapshot.audit_status == "COMPLETE"


def test_current_only_resolver_cannot_substitute_for_capture_time_authority():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    with pytest.raises(ValueError, match="capture-time authority"):
        validate_historical_authority_binding(fixture.authority, current_drift)


def test_missing_current_authority_is_diagnostic_only_not_historical_rewrite():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    result = replay_recorded_fixture(fixture, DECISION, current_authority_resolver=current_missing)
    assert len(result.replay_result.snapshot.accepted_event_ids) == 8
    assert result.authority_drift.status == AUTHORITY_DRIFT_MISSING


def test_matching_current_authority_is_diagnostic_only():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    diagnostic = diagnose_current_authority(fixture.authority, current_match)
    assert diagnostic.status == AUTHORITY_DRIFT_MATCH
    assert diagnostic.differences == ()


def test_current_authority_drift_does_not_mutate_historical_snapshot_hash():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    matching = replay_recorded_fixture(fixture, DECISION, current_authority_resolver=current_match)
    drifted = replay_recorded_fixture(fixture, DECISION, current_authority_resolver=current_drift)
    assert matching.replay_result.snapshot.canonical_hash == drifted.replay_result.snapshot.canonical_hash
    assert matching.fixture_digest == drifted.fixture_digest == FIXTURE_DIGEST


def test_missing_capture_time_authority_fails_closed():
    payload = raw_fixture()
    del payload["authority"]
    with pytest.raises(ValueError, match="capture-time authority"):
        RecordedMarketFixture.from_mapping(payload)


def test_unresolved_authority_mode_fails_closed():
    payload = raw_fixture()
    payload["authority"]["authority_mode"] = "VERSION_REF"
    with pytest.raises(ValueError, match="only embedded capture-time authority"):
        RecordedMarketFixture.from_mapping(payload)


def test_tampered_embedded_authority_with_stale_digest_fails_loud():
    payload = raw_fixture()
    payload["authority"]["adapter_id"] = "tampered"
    with pytest.raises(ValueError, match="authority digest mismatch"):
        RecordedMarketFixture.from_mapping(payload)


def test_wrong_historical_source_endpoint_binding_fails_closed():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    resolver = fixture.historical_authority_resolver()
    assert resolver(
        fixture.authority.source_token,
        "github.contents:OTHER.csv",
        fixture.authority.market,
    ) is None


def test_available_at_after_observed_at_fails_closed():
    payload = raw_fixture()
    payload["available_at"] = "2026-09-10T09:35:34.000000Z"
    with pytest.raises(ValueError, match="available_at cannot be after observed_at"):
        RecordedMarketFixture.from_mapping(payload)


def test_naive_observed_at_fails_closed():
    payload = raw_fixture()
    payload["observed_at"] = "2026-09-10T09:35:33"
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        RecordedMarketFixture.from_mapping(payload)


def test_row_tamper_with_stale_rows_digest_fails_loud():
    payload = raw_fixture()
    payload["rows"][0]["close"] = "999.0"
    with pytest.raises(ValueError, match="invalid OHLC envelope|rows digest mismatch"):
        RecordedMarketFixture.from_mapping(payload)


def test_fixture_metadata_tamper_with_stale_fixture_digest_fails_loud():
    payload = raw_fixture()
    payload["symbol"] = "MSFT"
    with pytest.raises(ValueError, match="fixture digest mismatch"):
        RecordedMarketFixture.from_mapping(payload)


def test_decision_before_conservative_capture_seal_cannot_see_recorded_rows():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    result = replay_recorded_fixture(fixture, BEFORE_CAPTURE)
    assert result.replay_result.snapshot.accepted_event_ids == ()
    assert result.replay_result.snapshot.pattern_instances == ()


def test_identical_recorded_fixture_replay_is_100_of_100_deterministic():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    hashes = [
        replay_recorded_fixture(fixture, DECISION).replay_result.snapshot.canonical_hash
        for _ in range(100)
    ]
    assert len(set(hashes)) == 1


def test_recorded_fixture_replay_has_no_side_effects_and_no_example_pattern_promotion():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    result = replay_recorded_fixture(fixture, DECISION).replay_result
    assert result.side_effect_count == 0
    assert result.snapshot.pattern_instances == ()


def test_materialized_events_bind_capture_digest_and_do_not_invent_published_at():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    events = fixture.materialize_events()
    assert len(events) == 8
    assert all(event.published_at is None for event in events)
    assert all(event.payload["recorded_authority_digest"] == AUTHORITY_DIGEST for event in events)
    assert all(event.available_at == fixture.available_at for event in events)
    assert all(event.observed_at == fixture.observed_at for event in events)


def test_admitted_recorded_event_persists_digest_bound_authority_reference():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    store = InMemoryEventStore(source_authority_resolver=fixture.historical_authority_resolver())
    event = fixture.materialize_events()[0]
    assert store.append(event) == "ACCEPTED"
    stored = store.events[0]
    assert stored.source_authority_ref.endswith(f"#sha256:{AUTHORITY_DIGEST}")
    assert stored.source_adapter_id == "github_content"
    assert stored.source_upstream_lineage_id == "getdata_finance"


def test_derived_pattern_lineage_reaches_capture_time_authority_binding():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    authority = fixture.authority
    observed = fixture.observed_at
    provider_event = EventRecord(
        event_id="recorded-provider-abnormality",
        event_type="MARKET_ABNORMALITY",
        entity_id="AAPL",
        theme_id=None,
        occurred_at=observed - timedelta(days=1),
        event_time=observed - timedelta(days=1),
        published_at=None,
        available_at=observed,
        observed_at=observed,
        created_at=observed,
        source_id=fixture.source_query,
        payload={
            "gap_zscore": 3.0,
            "rvol": 3.0,
            "rs_jump": 12.0,
            "turnover_percentile": 95.0,
            "grounded_catalyst_present": False,
            "recorded_authority_digest": AUTHORITY_DIGEST,
        },
        source_kind="PROVIDER",
        source_token=authority.source_token,
        endpoint_id=authority.endpoint_id,
        market=authority.market,
        trace_id=f"trace:recorded-fixture:{fixture.fixture_id}",
    )
    engine = ReplayBaselineEngine(
        source_authority_resolver=fixture.historical_authority_resolver()
    )
    assert engine.ingest(provider_event) == "ACCEPTED"
    snapshot = engine.snapshot(observed)
    assert len(snapshot.pattern_instances) == 1
    derived = next(
        item for item in engine.store.events if item.source_kind == "ENGINE_DERIVED"
    )
    raw = next(
        item for item in engine.store.events if item.event_id == provider_event.event_id
    )
    assert derived.parent_event_ids == (provider_event.event_id,)
    assert raw.source_authority_ref.endswith(f"#sha256:{AUTHORITY_DIGEST}")
    assert snapshot.pattern_instances[0].payload["entry_gate"] == "CLOSED"


def test_future_dated_recorded_row_fails_even_with_fresh_digests():
    payload = raw_fixture()
    payload["rows"][-1]["datetime"] = "2026-09-11T12:00:00+00:00"
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="row datetime cannot be after available_at"):
        RecordedMarketFixture.from_mapping(payload)


def test_embedded_authority_must_be_co_captured_with_observation():
    payload = raw_fixture()
    payload["authority"]["captured_at"] = "2026-09-10T09:35:32.000000Z"
    _rehash_all(payload)
    with pytest.raises(ValueError, match="captured_at must equal observed_at"):
        RecordedMarketFixture.from_mapping(payload)


def test_missing_bar_timestamp_semantics_fails_closed_instead_of_defaulting():
    payload = raw_fixture()
    del payload["time_semantics"]["bar_timestamp_semantic"]
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="time_semantics schema mismatch"):
        RecordedMarketFixture.from_mapping(payload)


def test_semantic_inflation_session_claim_fails_closed_with_fresh_digest():
    payload = raw_fixture()
    payload["time_semantics"]["session_semantics_claimed"] = True
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="must not claim session semantics"):
        RecordedMarketFixture.from_mapping(payload)


def test_source_commit_time_after_capture_availability_fails_closed():
    payload = raw_fixture()
    payload["time_semantics"]["source_commit_time"] = "2026-09-10T09:35:34.000000Z"
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="source_commit_time cannot be after available_at"):
        RecordedMarketFixture.from_mapping(payload)


def test_duplicate_or_reordered_bar_time_fails_even_with_fresh_digests():
    payload = raw_fixture()
    payload["rows"][1]["datetime"] = payload["rows"][0]["datetime"]
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="strictly increasing and unique"):
        RecordedMarketFixture.from_mapping(payload)


def test_invalid_ohlc_envelope_fails_even_with_fresh_digests():
    payload = raw_fixture()
    payload["rows"][0]["high"] = "200.0"
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="invalid OHLC envelope"):
        RecordedMarketFixture.from_mapping(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ref", "0" * 40, "query ref must equal pinned authority source commit"),
        ("path", "OTHER.csv", "source_query does not match canonical source tuple"),
        ("lines", "99-100", "query lines do not match recorded source-slice lines"),
    ],
)
def test_cross_field_provenance_mismatch_fails_even_with_fresh_digest(field, value, message):
    payload = raw_fixture()
    payload["query_params"][field] = value
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match=message):
        RecordedMarketFixture.from_mapping(payload)
