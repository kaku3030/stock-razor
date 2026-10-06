from datetime import datetime, timedelta, timezone
import pytest
from src.services.live_feed.futu_k1m_forming_accumulator import FutuK1MFormingAccumulator
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar


def test_bridge_rejects_forming_minute():
    a=FutuK1MFormingAccumulator(); _, forming=a.ingest({"code":"US.AMD","time_key":"2026-10-05 10:52:00","open":100,"high":101,"low":99,"close":100.5,"volume":10,"turnover":1000})
    with pytest.raises(ValueError, match="forming"):
        closed_futu_minute_to_bar(forming, received_at=datetime.now(timezone.utc))


def test_bridge_preserves_closed_ohlcv_and_blocks_signal_permission():
    a=FutuK1MFormingAccumulator(); a.ingest({"code":"US.AMD","time_key":"2026-10-05 10:53:00","open":100,"high":101,"low":99,"close":100.5,"volume":10,"turnover":1000}); closed,_=a.ingest({"code":"US.AMD","time_key":"2026-10-05 10:54:00","open":100.5,"high":102,"low":100,"close":101,"volume":5,"turnover":500})
    b=closed_futu_minute_to_bar(closed, received_at=datetime.now(timezone.utc))
    assert b.is_closed and b.is_complete and b.close == 100.5 and b.volume == 10
    assert b.bar_start == datetime(2026, 10, 5, 14, 52, tzinfo=timezone.utc)
    assert "TIMESTAMP_MISMATCH" not in b.quality_flags
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in b.quality_flags
    assert b.health.signal_permission.value == "blocked"


def test_bridge_uses_dst_aware_us_eastern_binding_in_winter():
    a=FutuK1MFormingAccumulator(); a.ingest({"code":"US.AMD","time_key":"2026-01-05 10:53:00","open":100,"high":101,"low":99,"close":100.5,"volume":10,"turnover":1000}); closed,_=a.ingest({"code":"US.AMD","time_key":"2026-01-05 10:54:00","open":100.5,"high":102,"low":100,"close":101,"volume":5,"turnover":500})
    b=closed_futu_minute_to_bar(closed, received_at=datetime.now(timezone.utc))
    assert b.bar_start == datetime(2026, 1, 5, 15, 52, tzinfo=timezone.utc)
    assert b.health.signal_permission.value == "blocked"


def test_us_intraday_provider_end_labels_map_to_canonical_intervals():
    received = datetime(2026, 10, 5, 20, 0, 1, tzinfo=timezone.utc)
    for raw_label, expected_start, expected_end in (
        (
            "2026-10-05 09:31:00",
            datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 10, 5, 13, 31, tzinfo=timezone.utc),
        ),
        (
            "2026-10-05 16:00:00",
            datetime(2026, 10, 5, 19, 59, tzinfo=timezone.utc),
            datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc),
        ),
    ):
        a = FutuK1MFormingAccumulator()
        a.ingest({
            "code": "US.AMD",
            "time_key": raw_label,
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100.5,
            "volume": 10,
            "turnover": 1000,
        })
        label = datetime.strptime(raw_label, "%Y-%m-%d %H:%M:%S")
        later = (label.replace(second=0) + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        closed, _ = a.ingest({
            "code": "US.AMD",
            "time_key": later,
            "open": 100.5,
            "high": 102,
            "low": 100,
            "close": 101,
            "volume": 5,
            "turnover": 500,
        })
        bar = closed_futu_minute_to_bar(closed, received_at=received)
        assert bar.bar_start == expected_start
        assert bar.bar_end == expected_end
        assert bar.source_timestamp == expected_end
