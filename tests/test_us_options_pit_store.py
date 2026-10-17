from datetime import datetime, timedelta, timezone
import gzip
import json

import pytest

from src.services.options_intelligence.futu_snapshot_adapter import (
    normalize_futu_snapshot_rows,
)
from src.services.options_intelligence.pit_store import (
    OptionsPitStore,
    build_futu_pit_snapshot,
)


NOW = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)


def _normalization(*, oi: int = 100):
    return normalize_futu_snapshot_rows(
        [
            {
                "code": "US.QQQ261007C760000",
                "option_valid": True,
                "option_type": "CALL",
                "option_strike_price": 760.0,
                "strike_time": "2026-10-07",
                "option_open_interest": oi,
                "option_gamma": 0.03,
                "option_implied_volatility": 22.5,
                "option_contract_multiplier": 100,
                "update_time": "2026-10-06 16:10:00",
            },
            {
                "code": "US.QQQ261007P760000",
                "option_valid": True,
                "option_type": "PUT",
                "option_strike_price": 760.0,
                "strike_time": "2026-10-07",
                "option_open_interest": 120,
                "option_gamma": "N/A",
                "option_implied_volatility": 23.0,
                "option_contract_multiplier": 100,
                "update_time": "2026-10-06 16:10:00",
            },
        ],
        underlying_symbol="QQQ",
    )


def _snapshot(*, oi: int = 100, collected_at: datetime = NOW):
    return build_futu_pit_snapshot(
        _normalization(oi=oi),
        underlying_symbol="QQQ",
        collected_at=collected_at,
        spot=756.2,
        spot_asof=datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc),
        spot_source="previous_regular_close",
    )


def test_pit_store_round_trip_preserves_unknown_oi_clock_and_rejections(tmp_path):
    store = OptionsPitStore(tmp_path)
    result = store.write(_snapshot())

    assert result.created is True
    assert result.path.exists()
    assert result.path.suffix == ".gz"
    assert result.compressed_bytes > 0

    restored = store.read(result.path)
    assert restored.underlying_symbol == "QQQ"
    assert restored.spot == pytest.approx(756.2)
    assert restored.spot_source == "previous_regular_close"
    assert restored.source_total == 2
    assert len(restored.observations) == 1
    assert len(restored.rejected) == 1
    row = restored.observations[0]
    assert row.open_interest == 100
    assert row.oi_asof is None
    assert row.quote_asof is not None
    assert row.implied_volatility == pytest.approx(0.225)


def test_identical_snapshot_is_idempotent_but_changed_oi_is_append_only(tmp_path):
    store = OptionsPitStore(tmp_path)

    first = store.write(_snapshot(oi=100))
    same = store.write(_snapshot(oi=100))
    changed = store.write(_snapshot(oi=101))

    assert first.created is True
    assert same.created is False
    assert same.path == first.path
    assert changed.created is True
    assert changed.path != first.path
    assert len(list(tmp_path.rglob("*.json.gz"))) == 2


def test_collection_timestamp_partitions_snapshots_without_overwrite(tmp_path):
    store = OptionsPitStore(tmp_path)

    first = store.write(_snapshot(collected_at=NOW))
    later = store.write(_snapshot(collected_at=NOW + timedelta(minutes=5)))

    assert first.path != later.path
    assert first.path.parent == later.path.parent
    assert len(list(tmp_path.rglob("*.json.gz"))) == 2


def test_digest_corruption_is_detected(tmp_path):
    store = OptionsPitStore(tmp_path)
    result = store.write(_snapshot())

    with gzip.open(result.path, "rt", encoding="utf-8") as handle:
        wrapper = json.load(handle)
    wrapper["snapshot"]["spot"] = 999.0
    with gzip.open(result.path, "wt", encoding="utf-8") as handle:
        json.dump(wrapper, handle)

    with pytest.raises(ValueError, match="SHA-256"):
        store.read(result.path)


def test_snapshot_rejects_naive_clock_and_unsafe_symbol():
    normalization = _normalization()

    with pytest.raises(ValueError, match="collected_at"):
        build_futu_pit_snapshot(
            normalization,
            underlying_symbol="QQQ",
            collected_at=datetime(2026, 10, 7, 11, 0),
            spot=756.2,
            spot_asof=NOW,
            spot_source="previous_regular_close",
        )

    with pytest.raises(ValueError, match="unsupported characters"):
        build_futu_pit_snapshot(
            normalization,
            underlying_symbol="../QQQ",
            collected_at=NOW,
            spot=756.2,
            spot_asof=NOW,
            spot_source="previous_regular_close",
        )
