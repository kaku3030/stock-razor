from datetime import datetime, timedelta, timezone
import json

from data_provider.cn_cloud_runtime_reader import read_cn_market_bars


NOW = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _payload(*, emitted_at=NOW - timedelta(seconds=30), safe=True):
    return {
        "schema": "stock_razor_cn_eastmoney_observation_v1",
        "repo_sha": "a" * 40,
        "runtime_instance_id": "cn-1",
        "sequence": 9,
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
            "512730": {
                "symbol": "512730",
                "status": "PASS",
                "timeframes": {
                    "1d": {
                        "status": "PASS",
                        "rows": [
                            {"label": "2026-09-29", "close": 1.72},
                            {"label": "2026-09-30", "close": 1.73},
                        ],
                        "provider_used": "tencent",
                        "provider_lineage": "tencent",
                        "fallback_from": "eastmoney",
                        "fallback_reason": "CloudObservationError",
                        "timestamp_semantic": "DAILY_DATE",
                        "currentness": "UNPROVEN",
                    },
                    "60m": {
                        "status": "PASS",
                        "rows": [{"label": "2026-09-30 15:00", "close": 1.73}],
                        "provider_used": "tencent",
                        "provider_lineage": "tencent",
                        "fallback_from": "eastmoney",
                        "fallback_reason": "CloudObservationError",
                        "timestamp_semantic": "UNKNOWN",
                        "currentness": "UNPROVEN",
                    },
                    "15m": {
                        "status": "PASS",
                        "rows": [{"label": "2026-09-30 15:00", "close": 1.73}],
                        "provider_used": "tencent",
                        "provider_lineage": "tencent",
                        "fallback_from": "eastmoney",
                        "fallback_reason": "CloudObservationError",
                        "timestamp_semantic": "UNKNOWN",
                        "currentness": "UNPROVEN",
                    },
                },
            }
        },
    }


def test_reads_cn_rows_with_provenance_and_safety(tmp_path):
    path = _write(tmp_path / "cn.json", _payload())

    result = read_cn_market_bars(
        "512730.SH",
        timeframe="1d",
        limit=1,
        path=path,
        now_utc=NOW,
    )

    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert result["symbol"] == "512730"
    assert result["timeframe"] == "1d"
    assert result["returned_row_count"] == 1
    assert result["rows"][0]["label"] == "2026-09-30"
    assert result["provider_used"] == "tencent"
    assert result["provider_lineage"] == "tencent"
    assert result["fallback_from"] == "eastmoney"
    assert result["timestamp_semantic"] == "DAILY_DATE"
    assert result["currentness"] == "UNPROVEN"
    assert result["intraday_timestamp_semantics_proven"] is False
    assert result["intraday_currentness_proven"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["read_latency_ms"] >= 0


def test_intraday_semantics_remain_unknown(tmp_path):
    path = _write(tmp_path / "cn.json", _payload())

    result = read_cn_market_bars(
        "512730",
        timeframe="15m",
        path=path,
        now_utc=NOW,
    )

    assert result["ok"] is True
    assert result["timestamp_semantic"] == "UNKNOWN"
    assert result["currentness"] == "UNPROVEN"


def test_stale_snapshot_is_explicit(tmp_path):
    path = _write(
        tmp_path / "cn.json",
        _payload(emitted_at=NOW - timedelta(minutes=10)),
    )

    result = read_cn_market_bars(
        "512730",
        path=path,
        now_utc=NOW,
        snapshot_max_age_seconds=180,
    )

    assert result["ok"] is True
    assert result["status"] == "STALE"
    assert result["source_age_seconds"] == 600


def test_unknown_symbol_is_not_fabricated(tmp_path):
    path = _write(tmp_path / "cn.json", _payload())

    result = read_cn_market_bars("159611", path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "NOT_FOUND"
    assert result["error"] == "SYMBOL_NOT_OBSERVED"


def test_safety_contract_drift_blocks(tmp_path):
    path = _write(tmp_path / "cn.json", _payload(safe=False))

    result = read_cn_market_bars("512730", path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID"
    assert result["error"] == "SAFETY_CONTRACT_VIOLATION"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_invalid_timeframe_and_limit_rejected(tmp_path):
    path = _write(tmp_path / "cn.json", _payload())

    bad_frame = read_cn_market_bars("512730", timeframe="1m", path=path, now_utc=NOW)
    bad_limit = read_cn_market_bars("512730", limit=0, path=path, now_utc=NOW)

    assert bad_frame["status"] == "INVALID_ARGUMENT"
    assert bad_frame["error"] == "UNSUPPORTED_TIMEFRAME"
    assert bad_limit["status"] == "INVALID_ARGUMENT"
    assert bad_limit["error"] == "INVALID_LIMIT"
