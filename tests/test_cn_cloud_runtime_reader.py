from datetime import datetime, timedelta, timezone
import json
import os

from data_provider.cn_cloud_runtime_reader import read_cn_market_data


NOW = datetime(2026, 10, 7, 7, 50, tzinfo=timezone.utc)


def _row(label, close):
    return {
        "label": label,
        "provider_label_raw": label,
        "open": close - 0.01,
        "close": close,
        "high": close + 0.02,
        "low": close - 0.02,
        "volume_raw": 1000,
        "volume_unit": "HAND",
        "amount_raw": None,
        "amount_unit": "UNAVAILABLE",
        "provider": "tencent",
        "quality_flags": [],
    }


def _payload(*, emitted_at=NOW - timedelta(seconds=10), safe=True):
    rows = [_row("2026-09-29", 1.6), _row("2026-09-30", 1.61)]
    return {
        "schema": "stock_razor_cn_eastmoney_observation_v1",
        "repo_sha": "a" * 40,
        "runtime_instance_id": "cn-1",
        "sequence": 7,
        "emitted_at_utc": emitted_at.isoformat(),
        "status": "PASS",
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "providers_used": ["tencent"],
        "provider_lineages": ["eastmoney", "tencent"],
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED" if safe else "ADMITTED",
        "live_trade": False,
        "symbols": {
            "159611": {
                "symbol": "159611",
                "status": "PASS",
                "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
                "providers_used": ["tencent"],
                "radar_admission": "BLOCKED",
                "live_trade": False,
                "timeframes": {
                    "1d": {
                        "status": "PASS",
                        "provider_used": "tencent",
                        "provider_lineage": "tencent",
                        "fallback_from": "eastmoney",
                        "fallback_reason": "CloudObservationError",
                        "timestamp_semantic": "DAILY_DATE",
                        "currentness": "UNPROVEN",
                        "row_count": 2,
                        "rows": rows,
                    },
                    "60m": {
                        "status": "PASS",
                        "provider_used": "tencent",
                        "provider_lineage": "tencent",
                        "fallback_from": "eastmoney",
                        "fallback_reason": "CloudObservationError",
                        "timestamp_semantic": "UNKNOWN",
                        "currentness": "UNPROVEN",
                        "row_count": 2,
                        "rows": rows,
                    },
                    "15m": {
                        "status": "PASS",
                        "provider_used": "tencent",
                        "provider_lineage": "tencent",
                        "fallback_from": "eastmoney",
                        "fallback_reason": "CloudObservationError",
                        "timestamp_semantic": "UNKNOWN",
                        "currentness": "UNPROVEN",
                        "row_count": 2,
                        "rows": rows,
                    },
                },
            }
        },
    }


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_reads_bounded_cn_rows_with_provenance(tmp_path):
    path = _write(tmp_path / "cn.json", _payload())

    result = read_cn_market_data(
        "159611",
        "1d",
        limit=1,
        path=path,
        now_utc=NOW,
    )

    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert result["symbol"] == "159611"
    assert result["timeframe"] == "1d"
    assert result["provider_used"] == "tencent"
    assert result["provider_lineage"] == "tencent"
    assert result["fallback_from"] == "eastmoney"
    assert result["timestamp_semantic"] == "DAILY_DATE"
    assert result["currentness"] == "UNPROVEN"
    assert result["total_row_count"] == 2
    assert result["row_count"] == 1
    assert result["rows"][0]["label"] == "2026-09-30"
    assert result["read_latency_ms"] >= 0


def test_symbol_aliases_are_normalized(tmp_path):
    path = _write(tmp_path / "cn.json", _payload())

    result = read_cn_market_data("SZ159611", "15m", path=path, now_utc=NOW)

    assert result["symbol"] == "159611"
    assert result["timestamp_semantic"] == "UNKNOWN"
    assert result["currentness"] == "UNPROVEN"


def test_stale_observation_is_explicit(tmp_path):
    path = _write(
        tmp_path / "cn.json",
        _payload(emitted_at=NOW - timedelta(minutes=10)),
    )

    result = read_cn_market_data("159611", "60m", path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["status"] == "STALE"
    assert result["source_age_seconds"] == 600


def test_safety_contract_violation_blocks(tmp_path):
    path = _write(tmp_path / "cn.json", _payload(safe=False))

    result = read_cn_market_data("159611", path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID"
    assert result["error"] == "SAFETY_CONTRACT_VIOLATION"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_invalid_timeframe_and_limit_fail_closed(tmp_path):
    path = _write(tmp_path / "cn.json", _payload())

    bad_frame = read_cn_market_data("159611", "1m", path=path, now_utc=NOW)
    bad_limit = read_cn_market_data("159611", "1d", limit=1000, path=path, now_utc=NOW)

    assert bad_frame["error"] == "UNSUPPORTED_TIMEFRAME"
    assert bad_limit["error"] == "INVALID_LIMIT"


def test_repeated_reads_hit_cache_and_atomic_replace_invalidates(tmp_path):
    path = tmp_path / "cn.json"
    _write(path, _payload())

    first = read_cn_market_data("159611", path=str(path), now_utc=NOW)
    second = read_cn_market_data("159611", path=str(path), now_utc=NOW)

    assert first["source_cache_hit"] is False
    assert second["source_cache_hit"] is True

    replacement = tmp_path / "cn.new.json"
    changed = _payload()
    changed["sequence"] = 8
    changed["symbols"]["159611"]["timeframes"]["1d"]["rows"][-1]["close"] = 1.7
    _write(replacement, changed)
    os.replace(replacement, path)

    third = read_cn_market_data("159611", path=str(path), now_utc=NOW)

    assert third["source_cache_hit"] is False
    assert third["sequence"] == 8
    assert third["rows"][-1]["close"] == 1.7
