import json
from pathlib import Path

import pytest

from src.services.strategy_lab.recorded_fixture import (
    RecordedMarketFixture,
    load_recorded_fixture,
)
from src.services.strategy_lab.replay_contract import stable_hash

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "strategy_lab"
    / "aapl_getdata_12h_recorded_fixture_v1.json"
)


def raw_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _rehash_authority(payload):
    authority = payload["authority"]
    authority["digest"] = stable_hash(
        {key: value for key, value in authority.items() if key != "digest"}
    )


def _rehash_fixture(payload):
    payload["rows_digest"] = stable_hash(payload["rows"])
    payload["fixture_digest"] = stable_hash(
        {key: value for key, value in payload.items() if key != "fixture_digest"}
    )


def _rehash_all(payload):
    _rehash_authority(payload)
    _rehash_fixture(payload)


def _source_query(payload):
    query = payload["query_params"]
    start, end = query["lines"].split("-")
    return (
        f"github://{query['repository']}/{query['path']}?ref={query['ref']}"
        f"#L{start}-L{end}"
    )


def test_source_query_is_bound_to_structured_source_tuple_even_with_fresh_digest():
    payload = raw_fixture()
    payload["source_query"] = "github://unrelated/repository/OTHER.csv?ref=" + (
        "0" * 40
    ) + "#L1-L2"
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="source_query does not match canonical source tuple"):
        RecordedMarketFixture.from_mapping(payload)


def test_repository_is_bound_to_authority_and_evidence_even_with_fresh_digest():
    payload = raw_fixture()
    payload["query_params"]["repository"] = "other-owner/other-repository"
    payload["source_query"] = _source_query(payload)
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="authority_ref does not bind canonical source tuple"):
        RecordedMarketFixture.from_mapping(payload)


@pytest.mark.parametrize("lines", ["0-9", "02-9", "9-2", "2 -9", "2-09", "2--9"])
def test_line_range_must_be_canonical_positive_ordered_even_with_fresh_digest(lines):
    payload = raw_fixture()
    payload["query_params"]["lines"] = lines
    payload["time_semantics"]["raw_source_slice_lines"] = lines
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="canonical positive N-M"):
        RecordedMarketFixture.from_mapping(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "authority_ref",
            "github:other-owner/other-repository@e9cebf45a7b68ca87e537c1f2d7f7ea312e79a1b:AAPL_12h.csv",
            "authority_ref does not bind canonical source tuple",
        ),
        (
            "evidence_ref",
            "other-owner/other-repository:AAPL_12h.csv@e9cebf45a7b68ca87e537c1f2d7f7ea312e79a1b",
            "evidence_ref does not bind canonical source tuple",
        ),
        (
            "license_ref",
            "other-owner/other-repository:LICENSE@e9cebf45a7b68ca87e537c1f2d7f7ea312e79a1b",
            "license_ref does not bind canonical repository and commit",
        ),
        (
            "license_ref",
            "getdata-finance/aapl-12h-ohlcv-stocks-historical-data:LICENSE@0000000000000000000000000000000000000000",
            "license_ref does not bind canonical repository and commit",
        ),
    ],
)
def test_authority_representations_are_cross_bound_with_fresh_digests(field, value, message):
    payload = raw_fixture()
    payload["authority"][field] = value
    _rehash_all(payload)
    with pytest.raises(ValueError, match=message):
        RecordedMarketFixture.from_mapping(payload)


def test_capture_provenance_cannot_contradict_structured_source_even_with_fresh_digest():
    payload = raw_fixture()
    payload["capture_provenance_ref"] = "unrelated provenance text"
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="capture_provenance_ref contradicts canonical source tuple"):
        RecordedMarketFixture.from_mapping(payload)


def test_canonical_source_query_is_persisted_as_event_source_id():
    fixture = load_recorded_fixture(FIXTURE_PATH)
    expected = _source_query(raw_fixture())
    events = fixture.materialize_events()
    assert events
    assert all(event.source_id == expected for event in events)


def test_loader_rejects_duplicate_top_level_json_key_before_schema_or_digest(tmp_path):
    path = tmp_path / "duplicate-top.json"
    path.write_text(
        '{"source_query":"first","source_query":"second"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key: source_query"):
        load_recorded_fixture(path)


def test_loader_rejects_duplicate_nested_provenance_key_before_schema_or_digest(tmp_path):
    path = tmp_path / "duplicate-nested.json"
    path.write_text(
        '{"query_params":{"repository":"owner/a","repository":"owner/b"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key: repository"):
        load_recorded_fixture(path)


def test_loader_rejects_non_finite_json_constant(tmp_path):
    path = tmp_path / "non-finite.json"
    path.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        load_recorded_fixture(path)


@pytest.mark.parametrize(
    "repository",
    ["owner", "/repo", "owner/", "owner/repo/extra", "owner/re po", "owner/repo?x"],
)
def test_repository_identity_rejects_noncanonical_encodings(repository):
    payload = raw_fixture()
    payload["query_params"]["repository"] = repository
    _rehash_fixture(payload)
    with pytest.raises(ValueError, match="query_params.repository"):
        RecordedMarketFixture.from_mapping(payload)
