from datetime import datetime, timezone
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from data_provider import cn_eastmoney_cloud_observer as observer
from data_provider.cn_eastmoney_cloud_observer import (
    SCHEMA,
    build_cn_cloud_observation,
    build_kline_url,
    build_tencent_kline_url,
    eastmoney_secid,
    observe_cn_cloud_symbol,
    parse_kline_rows,
    parse_tencent_kline_rows,
    tencent_symbol,
)


NOW = datetime(2026, 10, 7, 6, 45, tzinfo=timezone.utc)


def _eastmoney_payload(rows):
    return {"data": {"klines": rows}}


def _eastmoney_rows(prefix="2026-10-06"):
    return [
        f"{prefix} 09:45,10,10.5,10.8,9.9,1000,10500,0,0,0,0",
        f"{prefix} 10:00,10.5,10.7,10.9,10.4,1100,11700,0,0,0,0",
    ]


def _tencent_payload(symbol, timeframe):
    api_symbol = tencent_symbol(symbol)
    if timeframe == "1d":
        rows = [
            ["2026-10-02", "10", "10.2", "10.3", "9.9", "1000"],
            ["2026-10-06", "10.2", "10.4", "10.5", "10.1", "1200"],
        ]
        key = "day"
    else:
        rows = [
            ["202610060945", "10", "10.5", "10.8", "9.9", "1000.000", {}, "1.0"],
            ["202610061000", "10.5", "10.7", "10.9", "10.4", "1100.000", {}, "1.1"],
        ]
        key = f"m{timeframe[:-1]}"
    return {"code": 0, "data": {api_symbol: {key: rows}}}


def test_provider_symbol_mapping_covers_sh_sz_etf_and_stock():
    assert eastmoney_secid("512730") == "1.512730"
    assert eastmoney_secid("600519.SH") == "1.600519"
    assert eastmoney_secid("159611") == "0.159611"
    assert eastmoney_secid("000001.SZ") == "0.000001"
    assert tencent_symbol("512730") == "sh512730"
    assert tencent_symbol("159611") == "sz159611"


def test_build_urls_keep_read_only_provider_contracts():
    eastmoney = urlparse(build_kline_url("512730", "15m", limit=480))
    eastmoney_query = parse_qs(eastmoney.query)
    assert eastmoney.scheme == "https"
    assert eastmoney.netloc == "push2his.eastmoney.com"
    assert eastmoney_query["secid"] == ["1.512730"]
    assert eastmoney_query["klt"] == ["15"]
    assert eastmoney_query["fqt"] == ["0"]
    assert eastmoney_query["lmt"] == ["480"]

    tencent = urlparse(build_tencent_kline_url("159611", "60m", limit=240))
    tencent_query = parse_qs(tencent.query)
    assert tencent.scheme == "https"
    assert tencent.netloc == "ifzq.gtimg.cn"
    assert tencent_query["param"] == ["sz159611,m60,,240"]


def test_eastmoney_rows_preserve_unverified_provider_units():
    rows = parse_kline_rows(_eastmoney_payload(_eastmoney_rows()))

    assert len(rows) == 2
    assert rows[0]["label"] == "2026-10-06 09:45"
    assert rows[0]["provider"] == "eastmoney"
    assert rows[0]["volume_raw"] == 1000
    assert rows[0]["volume_unit"] == "PROVIDER_RAW_UNVERIFIED"
    assert rows[0]["amount_raw"] == 10500
    assert rows[0]["amount_unit"] == "PROVIDER_RAW_UNVERIFIED"
    assert rows[0]["quality_flags"] == []


def test_tencent_rows_preserve_hand_volume_and_raw_label():
    rows = parse_tencent_kline_rows(
        _tencent_payload("159611", "15m"),
        symbol="159611",
        timeframe="15m",
    )

    assert len(rows) == 2
    assert rows[0]["label"] == "2026-10-06 09:45"
    assert rows[0]["provider_label_raw"] == "202610060945"
    assert rows[0]["provider"] == "tencent"
    assert rows[0]["volume_raw"] == 1000
    assert rows[0]["volume_unit"] == "HAND"
    assert rows[0]["amount_raw"] is None
    assert rows[0]["amount_unit"] == "UNAVAILABLE"


def test_eastmoney_primary_does_not_call_fallback():
    calls = []

    def eastmoney(url):
        calls.append(url)
        if "klt=101" in url:
            return _eastmoney_payload([
                "2026-10-02,10,10.2,10.3,9.9,1000,10100,0,0,0,0",
                "2026-10-06,10.2,10.4,10.5,10.1,1200,12400,0,0,0,0",
            ])
        return _eastmoney_payload(_eastmoney_rows())

    def tencent(_url):
        raise AssertionError("fallback must not be called when primary passes")

    result = observe_cn_cloud_symbol(
        "159611",
        observed_at_utc=NOW,
        eastmoney_fetch_json=eastmoney,
        tencent_fetch_json=tencent,
    )

    assert result["status"] == "PASS"
    assert result["providers_used"] == ["eastmoney"]
    assert all(
        frame["provider_used"] == "eastmoney"
        and frame["fallback_from"] is None
        for frame in result["timeframes"].values()
    )
    assert result["timeframes"]["1d"]["timestamp_semantic"] == "DAILY_DATE"
    assert result["timeframes"]["15m"]["timestamp_semantic"] == "UNKNOWN"
    assert result["timeframes"]["60m"]["timestamp_semantic"] == "UNKNOWN"
    assert result["intraday_timestamp_semantics_proven"] is False
    assert result["intraday_currentness_proven"] is False
    assert len(calls) == 3


def test_eastmoney_failure_uses_independent_tencent_fallback():
    def eastmoney(_url):
        raise RuntimeError("remote disconnected")

    def tencent(url):
        if "day" in url:
            frame = "1d"
        elif "m60" in url:
            frame = "60m"
        else:
            frame = "15m"
        return _tencent_payload("159611", frame)

    result = observe_cn_cloud_symbol(
        "159611",
        observed_at_utc=NOW,
        eastmoney_fetch_json=eastmoney,
        tencent_fetch_json=tencent,
    )

    assert result["status"] == "PASS"
    assert result["providers_used"] == ["tencent"]
    for frame in result["timeframes"].values():
        assert frame["provider_used"] == "tencent"
        assert frame["provider_lineage"] == "tencent"
        assert frame["fallback_from"] == "eastmoney"
        assert frame["fallback_reason"] == "RuntimeError"
        assert frame["rows"]
        assert frame["rows"][-1]["volume_unit"] == "HAND"


def test_both_sources_failure_blocks_only_affected_timeframe():
    def eastmoney(url):
        if "klt=60" in url:
            raise RuntimeError("primary network")
        if "klt=101" in url:
            return _eastmoney_payload([
                "2026-10-06,10,10.2,10.3,9.9,1000,10100,0,0,0,0"
            ])
        return _eastmoney_payload(_eastmoney_rows())

    def tencent(url):
        if "m60" in url:
            raise RuntimeError("fallback network")
        raise AssertionError("fallback should only be called for failed 60m primary")

    result = observe_cn_cloud_symbol(
        "512730",
        observed_at_utc=NOW,
        eastmoney_fetch_json=eastmoney,
        tencent_fetch_json=tencent,
    )

    assert result["status"] == "PARTIAL"
    assert result["timeframes"]["60m"]["status"] == "BLOCKED"
    assert result["timeframes"]["60m"]["rows"] == []
    assert "RuntimeError|TENCENT:RuntimeError" in result["timeframes"]["60m"]["error"]
    assert result["timeframes"]["15m"]["status"] == "PASS"


def test_cloud_snapshot_is_research_only_and_lineage_explicit():
    def eastmoney(_url):
        raise RuntimeError("primary unavailable")

    def tencent(url):
        symbol = "512730" if "sh512730" in url else "159611"
        if "day" in url:
            frame = "1d"
        elif "m60" in url:
            frame = "60m"
        else:
            frame = "15m"
        return _tencent_payload(symbol, frame)

    result = build_cn_cloud_observation(
        ["512730", "159611", "512730"],
        repo_sha="a" * 40,
        runtime_instance_id="cn-runtime-1",
        sequence=1,
        observed_at_utc=NOW,
        eastmoney_fetch_json=eastmoney,
        tencent_fetch_json=tencent,
    )

    assert result["schema"] == SCHEMA
    assert result["status"] == "PASS"
    assert set(result["symbols"]) == {"512730", "159611"}
    assert result["provider_policy"] == "EASTMONEY_PRIMARY_TENCENT_FALLBACK"
    assert result["providers_used"] == ["tencent"]
    assert set(result["provider_lineages"]) == {"eastmoney", "tencent"}
    assert result["intraday_timestamp_semantics_proven"] is False
    assert result["intraday_currentness_proven"] is False
    assert result["research_only"] is True
    assert result["can_confirm_signal"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_http_json_retries_transient_disconnects(monkeypatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return b'{"data":{"klines":[]}}'

    def fake_urlopen(request, timeout):
        attempts.append(timeout)
        if len(attempts) < 3:
            raise ConnectionResetError("transient")
        return Response()

    sleeps = []
    monkeypatch.setattr(observer, "urlopen", fake_urlopen)

    payload = observer._http_json(
        "https://example.invalid",
        timeout_seconds=2,
        max_attempts=3,
        sleep_fn=sleeps.append,
    )

    assert payload == {"data": {"klines": []}}
    assert attempts == [2, 2, 2]
    assert sleeps == [0.25, 0.5]


def test_symbol_timeframes_are_observed_concurrently(monkeypatch):
    barrier = threading.Barrier(3, timeout=1.0)

    def fake_frame(code, timeframe, **kwargs):
        barrier.wait()
        return {
            "status": "PASS",
            "error": None,
            "row_count": 1,
            "rows": [{"label": timeframe}],
            "request_latency_ms": 1.0,
            "provider_used": "eastmoney",
            "provider_lineage": "eastmoney",
            "fallback_from": None,
            "fallback_reason": None,
            "timestamp_semantic": "DAILY_DATE" if timeframe == "1d" else "UNKNOWN",
            "currentness": "UNPROVEN",
            "adjustment": "NONE",
        }

    monkeypatch.setattr(observer, "_frame_observation", fake_frame)

    result = observer.observe_cn_cloud_symbol("512730", observed_at_utc=NOW)

    assert list(result["timeframes"]) == ["1d", "60m", "15m"]
    assert all(item["status"] == "PASS" for item in result["timeframes"].values())
