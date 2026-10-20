"""Round16 research-only helpers for ledger parity, regimes, and arm gates.

This module deliberately fails closed.  It does not download data, infer
provider finality, or turn a partial OpenD probe into a backtest result.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from tools.research import round13_radar_research as r13
from tools.research.round10_radar_replay import RISK_BUDGET, SECTOR
from tools.research.round14_srvp_fusion import _enrich

SEVEN_REGIMES = (
    "TREND_UP_STRONG",
    "TREND_UP_WEAK",
    "TREND_DOWN_STRONG",
    "TREND_DOWN_WEAK",
    "RANGE_WIDE",
    "RANGE_NARROW",
    "TRANSITION",
)
REGIME_GAP_STRONG = 0.02
REGIME_SLOPE_STRONG = 0.005
REGIME_RANGE_WIDE = 0.03


def canonicalize_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a deterministic ledger without changing trade values."""
    required = {"symbol", "signal_time", "protocol"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"ledger missing required columns: {sorted(missing)}")
    out = frame.copy()
    out["signal_time"] = pd.to_datetime(out["signal_time"], errors="raise")
    for column in ("entry_time", "exit_time"):
        if column in out:
            out[column] = pd.to_datetime(out[column], errors="raise")
    keys = ["protocol", "signal_time", "symbol"]
    for column in ("entry_time", "exit_time", "entry_index", "execution_timeframe"):
        if column in out:
            keys.append(column)
    return out.sort_values(keys, kind="mergesort").reset_index(drop=True)


def compare_protocol_ledgers(left: pd.DataFrame, right: pd.DataFrame, protocol: str = "III") -> dict:
    """Identify the first semantic difference between two protocol ledgers."""
    a = canonicalize_ledger(left[left.protocol == protocol])
    b = canonicalize_ledger(right[right.protocol == protocol])
    if len(a) != len(b):
        first = min(len(a), len(b))
        return {"status": "BLOCKED", "reason": "ROW_COUNT_MISMATCH", "first_index": first,
                "left_rows": len(a), "right_rows": len(b)}
    columns = [c for c in ("symbol", "signal_time", "entry_time", "exit_time",
                           "entry_index", "execution_timeframe", "entry_price",
                           "exit_price", "exit_reason", "net_pnl") if c in a and c in b]
    for index in range(len(a)):
        for column in columns:
            left_value, right_value = a.iloc[index][column], b.iloc[index][column]
            if pd.isna(left_value) and pd.isna(right_value):
                continue
            if str(left_value) != str(right_value):
                return {"status": "BLOCKED", "reason": "FIRST_FIELD_MISMATCH",
                        "first_index": index, "field": column,
                        "left": str(left_value), "right": str(right_value),
                        "left_key": {k: str(a.iloc[index][k]) for k in keys_present(a, index)},
                        "right_key": {k: str(b.iloc[index][k]) for k in keys_present(b, index)}}
    return {"status": "PASS", "rows": len(a), "protocol": protocol}


def keys_present(frame: pd.DataFrame, index: int) -> tuple[str, ...]:
    return tuple(c for c in ("symbol", "signal_time", "entry_time", "entry_index") if c in frame)


def classify_seven_state(d1: pd.DataFrame, hourly: pd.DataFrame, at: pd.Timestamp) -> str:
    """Classify using only the latest completed D1 and 1H rows before ``at``."""
    d_rows = d1[d1.time_key < at]
    h_rows = hourly[hourly.time_key < at]
    if d_rows.empty or h_rows.empty:
        return "UNKNOWN"
    d, h = d_rows.iloc[-1], h_rows.iloc[-1]
    fields = (d.get("ema20"), d.get("ema50"), d.get("ema20_slope"),
              h.get("ema20"), h.get("ema50"), h.get("ema20_slope"))
    if any(pd.isna(value) for value in fields):
        return "UNKNOWN"
    d_gap = float((d.ema20 - d.ema50) / d.close)
    h_gap = float((h.ema20 - h.ema50) / h.close)
    d_slope, h_slope = float(d.ema20_slope), float(h.ema20_slope)
    d_range = d1[d1.time_key < at].tail(20)
    h_range = hourly[hourly.time_key < at].tail(20)
    if len(d_range) < 20 or len(h_range) < 20:
        return "UNKNOWN"
    range_pct = max(float((d_range.high - d_range.low).mean() / d.close),
                    float((h_range.high - h_range.low).mean() / h.close))
    if d_gap > 0 and h_gap > 0 and d_slope > 0 and h_slope > 0:
        return "TREND_UP_STRONG" if d_gap >= REGIME_GAP_STRONG or d_slope >= REGIME_SLOPE_STRONG else "TREND_UP_WEAK"
    if d_gap < 0 and h_gap < 0 and d_slope < 0 and h_slope < 0:
        return "TREND_DOWN_STRONG" if abs(d_gap) >= REGIME_GAP_STRONG or abs(d_slope) >= REGIME_SLOPE_STRONG else "TREND_DOWN_WEAK"
    if abs(d_slope) <= 0.001 and abs(h_slope) <= 0.001:
        return "RANGE_WIDE" if range_pct >= REGIME_RANGE_WIDE else "RANGE_NARROW"
    return "TRANSITION"


def build_s1_srvp_signals(symbol: str, frames: dict[str, pd.DataFrame], hashes: dict[str, str]) -> pd.DataFrame:
    """Build standalone SRVP confirmations; no Radar signal list is consumed."""
    hourly = _enrich(frames["1H"])
    rows = []
    last = -10**9
    for index, bar in hourly.iterrows():
        if index - last < 5 or not bool(bar.near_val) or pd.isna(bar.val) or float(bar.val) <= 0 or float(bar.val) >= float(bar.close):
            continue
        rows.append({
            "protocol": "S1", "symbol": symbol, "sector": SECTOR[symbol],
            "market_regime": "UNKNOWN", "signal_time": bar.time_key,
            "signal_available_at": bar.time_key, "execution_timeframe": "1H",
            "entry_index": index + 1, "signal_close": float(bar.close),
            "stop_price": float(bar.val), "target_price": float(bar.close + 2 * (bar.close - bar.val)),
            "risk_budget": RISK_BUDGET, "rule": "SRVP_1H_near_VAL_close_above_VAL_and_open",
            "data_hash_1h": hashes["1H"], "data_hash_d1": hashes["D1"],
            "quality": "UNKNOWN_TIMEZONE_DST_CALENDAR_BAR_CLOSURE_PROVIDER_FINALITY",
        })
        last = index
    return pd.DataFrame(rows)


def qualify_s2_coverage(capture: Path, symbol: str) -> dict:
    """Gate S2 on actual five-timeframe files, including 1m."""
    timeframes = ("D1", "1H", "15m", "5m", "1m")
    rows = []
    for timeframe in timeframes:
        path = capture / f"US_{symbol}_{timeframe}_qfq_rth_20190101_20261016.csv"
        rows.append({"symbol": symbol, "timeframe": timeframe, "exists": path.exists(),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None})
    return {"status": "READY" if all(row["exists"] for row in rows) else "BLOCKED",
            "reason": None if all(row["exists"] for row in rows) else "MISSING_1M_OR_OTHER_TIMEFRAME",
            "coverage": rows}
