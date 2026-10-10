"""Compact fail-closed cross-market data-source status for the read-only MCP.

Reads only existing local canonical/cache readers. Does not query OpenD,
TickFlow, Eastmoney or Tencent, or imply trading/data-source admission.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from data_provider.cn_cloud_runtime_reader import read_cn_market_data
from data_provider.tickflow_cloud_probe_reader import read_tickflow_probe_health
from data_provider.us_canonical_runtime_reader import read_us_livefeed_health


def read_market_source_status(
    cn_symbol: str = "159611.SZ", *, now_utc: datetime | None = None,
) -> dict:
    started = perf_counter()
    now = now_utc or datetime.now(timezone.utc)
    safety = {
        "schema": "stock_razor_market_source_status_v0_1",
        "research_only": True,
        "can_confirm_signal": False,
        "provider_requests": 0,
        "model_inference_performed": False,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
    }

    if now.tzinfo is None or now.utcoffset() is None:
        return {**safety, "ok": False, "status": "INVALID_CLOCK", "sources": {}}

    def read(call, *args, **kwargs):
        try:
            result = call(*args, **kwargs)
            return result if isinstance(result, dict) else {"ok": False, "status": "INVALID"}
        except (OSError, ValueError, TypeError, RuntimeError):
            return {"ok": False, "status": "UNAVAILABLE"}

    us = read(read_us_livefeed_health, now_utc=now)
    cn = read(read_cn_market_data, cn_symbol, timeframe="15m", limit=1, now_utc=now)
    tf = read(read_tickflow_probe_health, now_utc=now)

    # Project only a narrow allowlist. Never return raw bars, provider payloads,
    # credentials, errors, filesystem paths, or unverifiable provider metrics.
    def enum(value, allowed):
        return value if isinstance(value, str) and value in allowed else "UNKNOWN"

    us_status = enum(us.get("status"), {"HEALTHY", "DEGRADED", "STALE", "UNAVAILABLE", "INVALID"})
    cn_status = enum(cn.get("status"), {"PASS", "BLOCKED", "STALE", "NO_DATA", "UNAVAILABLE", "INVALID", "INVALID_ARGUMENT"})
    tf_status = enum(tf.get("status"), {"PROBE_ONLY", "STALE", "UNAVAILABLE", "INVALID"})
    us_ok = us.get("ok") is True and us_status == "HEALTHY"
    cn_ok = cn.get("ok") is True and cn_status == "PASS"
    tf_evidence = tf.get("ok") is True and tf_status == "PROBE_ONLY"

    result = {
        **safety,
        "ok": us_ok or cn_ok,
        "status": "OBSERVATION_ONLY" if (us_ok or cn_ok or tf_evidence) else "UNAVAILABLE_OR_UNQUALIFIED",
        "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
        "sources": {
            "us_opend": {
                "status": us_status,
                "observation_healthy": us_ok,
                "provider_to_radar_e2e": "NOT_VERIFIED",
            },
            "cn_eastmoney_tencent": {
                "status": cn_status,
                "symbol": cn.get("symbol") if cn.get("symbol") == cn_symbol else None,
                "timeframe": "15m",
                "observation_available": cn_ok,
                "intraday_currentness_proven": False,
            },
            "cn_tickflow": {
                "status": tf_status,
                "isolated_probe_evidence_available": tf_evidence,
                "production_feed_connected": False,
                "tickflow_to_radar_e2e": "NOT_VERIFIED",
                "data_admission": "BLOCKED",
            },
        },
        "read_latency_ms": round((perf_counter() - started) * 1000, 3),
    }
    return result
