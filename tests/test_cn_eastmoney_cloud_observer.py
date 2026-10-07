from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from data_provider.cn_eastmoney_cloud_observer import (
    SCHEMA,
    build_cn_cloud_observation,
    build_kline_url,
    eastmoney_secid,
    observe_eastmoney_symbol,
    parse_kline_rows,
)


NOW = datetime(2026, 10, 7, 6, 45, tzinfo=timezone.utc)


def _payload(rows):
    return {"data": {"klines": rows}}


def _rows(prefix="2026-10-06"):
    return [
        f"{prefix} 09:45,10,10.5,10.8,9.9,1000,10500,0,0,0,0",
        f"{prefix} 10:00,10.5,10.7,10.9,10.4,1100,11700,0,0,0,0",
    ]


def test_secid_mapping_covers_sh_sz_etf_and_stock():
    assert eastmoney_secid("512730") == "1.512730"
    assert eastmoney_secid("600519.SH") == "1.600519"
    assert eastmoney_secid("159611") == "0.159611"
    assert eastmoney_secid("000001.SZ") == "0.000001"


def test_build_url_uses_read_only_kline_contract():
    url = build_kline_url("512730", "15m", limit=480)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "push2his.eastmoney.com"
    assert query["secid"] == ["1.512730"]
    assert query["klt"] == ["15"]
    assert query["fqt"] == ["0"]
    assert query["lmt"] == ["480"]
    assert "fields1" in query
    assert "fields2" in query


def test_parse_rows_preserves_provider_label_and_raw_volume_amount():
    rows = parse_kline_rows(_payload(_rows()))

    assert len(rows) == 2
    assert rows[0]["label"] == "2026-10-06 09:45"
    assert rows[0]["open"] == 10.0
    assert rows[0]["close"] == 10.5
    assert rows[0]["volume_raw"] == 1000
    assert rows[0]["amount_raw"] == 10500
    assert rows[0]["quality_flags"] == []


def test_parse_rows_rejects_duplicate_or_out_of_order_labels():
    with pytest.raises(Exception):
        parse_kline_rows(_payload([
            _rows()[1],
            _rows()[0],
        ]))


def test_intraday_semantics_and_currentness_remain_unproven():
    calls = []

    def fetch(url):
        calls.append(url)
        if "klt=101" in url:
            return _payload([
                "2026-10-02,10,10.2,10.3,9.9,1000,10100,0,0,0,0",
                "2026-10-06,10.2,10.4,10.5,10.1,1200,12400,0,0,0,0",
            ])
        return _payload(_rows())

    result = observe_eastmoney_symbol("159611", observed_at_utc=NOW, fetch_json=fetch)

    assert result["status"] == "PASS"
    assert result["timeframes"]["1d"]["timestamp_semantic"] == "DAILY_DATE"
    assert result["timeframes"]["15m"]["timestamp_semantic"] == "UNKNOWN"
    assert result["timeframes"]["60m"]["timestamp_semantic"] == "UNKNOWN"
    assert result["intraday_timestamp_semantics_proven"] is False
    assert result["intraday_currentness_proven"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert len(calls) == 3


def test_one_timeframe_failure_is_partial_not_fabricated_pass():
    def fetch(url):
        if "klt=60" in url:
            raise RuntimeError("network")
        if "klt=101" in url:
            return _payload([
                "2026-10-06,10,10.2,10.3,9.9,1000,10100,0,0,0,0"
            ])
        return _payload(_rows())

    result = observe_eastmoney_symbol("512730", observed_at_utc=NOW, fetch_json=fetch)

    assert result["status"] == "PARTIAL"
    assert result["timeframes"]["60m"]["status"] == "BLOCKED"
    assert result["timeframes"]["60m"]["rows"] == []
    assert result["timeframes"]["15m"]["status"] == "PASS"


def test_cloud_snapshot_is_research_only_and_provenance_bound():
    def fetch(url):
        if "klt=101" in url:
            return _payload([
                "2026-10-06,10,10.2,10.3,9.9,1000,10100,0,0,0,0"
            ])
        return _payload(_rows())

    result = build_cn_cloud_observation(
        ["512730", "159611", "512730"],
        repo_sha="a" * 40,
        runtime_instance_id="cn-runtime-1",
        sequence=1,
        observed_at_utc=NOW,
        fetch_json=fetch,
    )

    assert result["schema"] == SCHEMA
    assert result["status"] == "PASS"
    assert set(result["symbols"]) == {"512730", "159611"}
    assert result["provider"] == "eastmoney"
    assert result["provider_lineage"] == "eastmoney"
    assert result["intraday_timestamp_semantics_proven"] is False
    assert result["intraday_currentness_proven"] is False
    assert result["research_only"] is True
    assert result["can_confirm_signal"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
