"""Offline regression for layered benchmark evidence semantics."""

from scripts import benchmark_cloud_fast_path_reads as benchmark


def test_us_callback_latency_is_not_laundered_into_provider_network_latency(monkeypatch):
    monkeypatch.setattr(
        benchmark, "read_us_livefeed_health",
        lambda: {"status": "HEALTHY", "provider_callback_latency_ms": 2.75},
    )
    monkeypatch.setattr(
        benchmark, "read_us_market_snapshots",
        lambda symbols: {"status": "PASS", "read_latency_ms": 6},
    )
    monkeypatch.setattr(
        benchmark, "read_us_radar_analysis",
        lambda symbols: {
            "status": "PASS",
            "read_latency_ms": 3,
            "radar_analysis_latency_ms": 80,
            "data_to_radar_latency_ms": 200,
        },
    )
    row = benchmark.benchmark_us(["AMD"], 1)[0]
    assert row.provider == "futu-opend"
    assert row.provider_latency_ms is None
    assert row.provider_callback_processing_latency_ms == 2.75
    assert row.canonical_latency_ms == 6
    assert row.radar_analysis_latency_ms == 80
    assert row.data_to_radar_latency_ms == 200
    assert row.retry_count is None
    assert row.fallback_count is None
    assert row.mcp_latency_ms is None
    assert row.e2e_latency_ms is None
    assert row.radar_admission == "BLOCKED"


def test_cn_missing_read_latency_cannot_be_summed_as_zero(monkeypatch):
    def cn_read(symbol, **kwargs):
        return (
            {"status": "PASS", "provider_used": "eastmoney", "read_latency_ms": 5}
            if symbol == "512730"
            else {"status": "PASS", "provider_used": "tencent"}
        )
    monkeypatch.setattr(benchmark, "read_cn_market_data", cn_read)
    monkeypatch.setattr(
        benchmark, "read_cn_radar_analysis",
        lambda symbols: {
            "status": "PASS",
            "radar_analysis_latency_ms": None,
            "data_to_radar_latency_ms": None,
            "read_latency_ms": 2,
        },
    )
    row = benchmark.benchmark_cn(["512730", "159611"], "15m", 1)[0]
    assert row.canonical_latency_ms is None
    assert row.provider_latency_ms is None
    assert row.provider_request_path_latency_ms is None
    assert row.fallback_count is None
    assert row.radar_analysis_latency_ms is None
    assert row.success is True


def test_cn_provider_request_path_cannot_impersonate_network_latency(monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "read_cn_market_data",
        lambda symbol, **kwargs: {
            "status": "PASS",
            "provider_used": "tencent",
            "fallback_from": "eastmoney",
            "provider_request_latency_ms": 1300,
            "read_latency_ms": 4,
        },
    )
    monkeypatch.setattr(
        benchmark,
        "read_cn_radar_analysis",
        lambda symbols: {"status": "PASS", "read_latency_ms": 3},
    )
    row = benchmark.benchmark_cn(["159611"], "15m", 1)[0]
    assert row.provider == "tencent"
    assert row.provider_latency_ms is None
    assert row.provider_request_path_latency_ms == 1300
    assert row.fallback_count == 1
    assert row.fallback_provider == "tencent"
    assert row.radar_admission == "BLOCKED"


def test_nonfinite_or_boolean_runtime_values_are_not_measured():
    assert benchmark._number({"read_latency_ms": True}, "read_latency_ms") is None
    assert benchmark._number({"read_latency_ms": float("nan")}, "read_latency_ms") is None
    assert benchmark._number({"read_latency_ms": float("inf")}, "read_latency_ms") is None


def test_cn_source_diagnostics_are_per_symbol_and_never_publish_bars(monkeypatch):
    payloads = {
        "159611": {
            "status": "PASS",
            "provider_used": "eastmoney",
            "fallback_from": None,
            "timestamp_semantic": "UNKNOWN",
            "currentness": "UNPROVEN",
            "symbol_intraday_timestamp_semantics_proven": False,
            "symbol_intraday_currentness_proven": False,
            "source_age_seconds": 40.0,
            "total_row_count": 120,
            "rows": [{"close": 11.11}],
            "failure_reason": "DO_NOT_PRINT",
        },
        "518880": {
            "status": "PASS",
            "provider_used": "tencent",
            "fallback_from": "eastmoney",
            "timestamp_semantic": "BAR_END",
            "currentness": "PROVEN",
            "symbol_intraday_timestamp_semantics_proven": True,
            "symbol_intraday_currentness_proven": True,
            "source_age_seconds": 5.0,
            "total_row_count": 480,
            "rows": [{"close": 22.22}],
            "api_key": "SECRET",
        },
    }
    monkeypatch.setattr(
        benchmark,
        "read_cn_market_data",
        lambda symbol, **kwargs: payloads[symbol],
    )
    result = benchmark.cn_symbol_read_diagnostics(
        ["159611", "518880", "518880"], "15m"
    )
    assert result["scope"] == "CN_READ_ONLY_SOURCE_DIAGNOSTIC_NOT_ADMISSION"
    assert result["requested_symbols"] == 2
    assert result["data_qualification"] == "NOT_VERIFIED"
    assert result["symbols"]["159611"]["symbol_currentness_proven"] is False
    assert result["symbols"]["518880"]["currentness"] == "PROVEN"
    assert result["symbols"]["518880"]["provider_used"] == "tencent"
    assert result["symbols"]["518880"]["fallback_from"] == "eastmoney"
    import json
    encoded = json.dumps(result)
    assert "DO_NOT_PRINT" not in encoded
    assert "SECRET" not in encoded
    assert "close" not in encoded
    assert "11.11" not in encoded
    assert "22.22" not in encoded
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_cn_diagnostics_unknown_and_stale_remain_visible(monkeypatch):
    monkeypatch.setattr(
        benchmark, "read_cn_market_data",
        lambda symbol, **kwargs: {
            "status": "STALE", "provider_used": "untrusted",
            "timestamp_semantic": "some-new-semantic",
            "currentness": "UNPROVEN",
            "source_age_seconds": float("inf"),
            "total_row_count": True,
        },
    )
    row = benchmark.cn_symbol_read_diagnostics(["159611"], "15m")["symbols"]["159611"]
    assert row["read_status"] == "STALE"
    assert row["provider_used"] == "UNKNOWN"
    assert row["timestamp_semantic"] == "UNKNOWN"
    assert row["symbol_currentness_proven"] is False
    assert row["source_age_seconds"] is None
    assert row["observed_row_count"] is None
    assert row["radar_admission"] == "BLOCKED"


def test_us_cloud_diagnostics_distinguish_closed_market_and_missing_symbols(monkeypatch):
    monkeypatch.setattr(
        benchmark, "read_us_livefeed_health",
        lambda: {
            "status": "DEGRADED",
            "market_state_us": "CLOSED",
            "delivery_mode": "UNPROVEN",
            "bar_closure": "UNPROVEN",
            "canonical_export_status": "BLOCKED",
            "realtime_delivery_evidence": False,
            "bar_closure_proven": False,
            "secret": "DO_NOT_PRINT",
        },
    )
    monkeypatch.setattr(
        benchmark, "read_us_market_snapshots",
        lambda symbols: {
            "status": "STALE",
            "source_age_seconds": 600.0,
            "data_available": True,
            "symbols": {
                "AMD": {
                    "counts": {"1m": 20, "5m": 4, "15m": 1, "1h": 0},
                    "latest": {"1m": {"close": 101.25}},
                },
            },
        },
    )
    monkeypatch.setattr(
        benchmark, "read_us_radar_analysis",
        lambda symbols: {
            "status": "STALE",
            "poll_status": "BLOCKED",
            "source_age_seconds": 999.0,
            "failure_reason": "SECRET_ERROR",
        },
    )
    result=benchmark.us_cloud_read_diagnostics(["AMD", "NVDA"])
    assert result["scope"] == "US_READ_ONLY_SOURCE_DIAGNOSTIC_NOT_ADMISSION"
    assert result["market_state_us"] == "CLOSED"
    assert result["livefeed_status"] == "DEGRADED"
    assert result["canonical_snapshot_status"] == "STALE"
    assert result["radar_poll_status"] == "BLOCKED"
    assert result["symbols"]["AMD"]["bar_counts"]["1m"] == 20
    assert result["symbols"]["AMD"]["any_bars_observed"] is True
    assert result["symbols"]["NVDA"]["symbol_present"] is False
    assert result["symbols"]["NVDA"]["any_bars_observed"] is False
    assert result["data_qualification"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"
    import json
    encoded=json.dumps(result)
    for secret in ("DO_NOT_PRINT", "SECRET_ERROR", "close", "101.25"):
        assert secret not in encoded


def test_us_diagnostics_reject_unrecognized_status_and_bad_counts(monkeypatch):
    monkeypatch.setattr(
        benchmark, "read_us_livefeed_health",
        lambda: {"status": "PROVIDER_VERIFIED", "market_state_us": "CUSTOM"},
    )
    monkeypatch.setattr(
        benchmark, "read_us_market_snapshots",
        lambda symbols: {
            "status": "PASS",
            "symbols": {"QQQ": {"counts": {
                "1m": True, "5m": -1, "15m": "2", "1h": 0
            }}},
        },
    )
    monkeypatch.setattr(
        benchmark, "read_us_radar_analysis",
        lambda symbols: {"status": "OPEN_TRADE", "poll_status": "GREAT"},
    )
    out=benchmark.us_cloud_read_diagnostics(["QQQ"])
    assert out["livefeed_status"] == "UNKNOWN"
    assert out["market_state_us"] == "UNKNOWN"
    assert out["radar_status"] == "UNKNOWN"
    assert out["symbols"]["QQQ"]["bar_counts"] == {
        "1m": None, "5m": None, "15m": None, "1h": 0
    }
    assert out["symbols"]["QQQ"]["any_bars_observed"] is False
    assert out["can_confirm_signal"] is False
