"""Offline TickFlow/reference closed-bar *comparison*, not source qualification.

Input is an explicitly curated, minimal normalized JSON fixture, NEVER raw
provider responses. No SDK, credentials, network, cloud or canonical writes.
Even perfect agreement cannot prove entitlement, latency, closure or continuity.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = "stock_razor_cn_offline_bar_fixture_v0_1"
ALLOWED_TIMEFRAMES = {"15m", "60m"}
ALLOWED_SOURCES = {"TICKFLOW", "EASTMONEY", "TENCENT"}
FIELDS = ("open", "high", "low", "close", "volume")
BAR_KEYS = {"bar_end_utc", *FIELDS}
TOP_KEYS = {
    "schema", "fixture_origin", "source", "symbol", "timeframe",
    "timestamp_semantic", "adjustment", "volume_unit", "rows",
}
MAX_FILE_BYTES = 1_000_000
MAX_ROWS = 500
CN_TZ = ZoneInfo("Asia/Shanghai")


class FixtureError(ValueError):
    pass


def _finite_number(value, *, positive=False):
    return (
        type(value) in (int, float) and math.isfinite(value)
        and (value > 0 if positive else value >= 0)
    )


def _session_bar_end(dt: datetime, timeframe: str) -> bool:
    local = dt.astimezone(CN_TZ)
    if local.weekday() > 4:
        return False
    minute = local.hour * 60 + local.minute
    if timeframe == "15m":
        return (585 <= minute <= 690 or 795 <= minute <= 900) and minute % 15 == 0
    return minute in (630, 690, 840, 900)


def _parse_bar_end(value, timeframe: str) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise FixtureError("INVALID_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FixtureError("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FixtureError("NAIVE_TIMESTAMP")
    if parsed.utcoffset().total_seconds() != 0:
        raise FixtureError("TIMESTAMP_MUST_BE_UTC")
    if parsed.second != 0 or parsed.microsecond != 0 or not _session_bar_end(parsed, timeframe):
        raise FixtureError("BAR_END_OUTSIDE_SESSION")
    return parsed.astimezone(timezone.utc).isoformat()


def _read_fixture(path: str) -> dict:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise FixtureError("FIXTURE_UNAVAILABLE") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise FixtureError("FIXTURE_TOO_LARGE")
    try:
        doc = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise FixtureError("INVALID_JSON") from exc
    if not isinstance(doc, dict) or set(doc) != TOP_KEYS:
        raise FixtureError("INVALID_FIXTURE_SCHEMA")
    if doc["schema"] != SCHEMA:
        raise FixtureError("UNSUPPORTED_SCHEMA")
    if doc["fixture_origin"] not in ("REAL_CAPTURED", "SYNTHETIC"):
        raise FixtureError("INVALID_FIXTURE_ORIGIN")
    if not isinstance(doc["source"], str) or doc["source"] not in ALLOWED_SOURCES:
        raise FixtureError("INVALID_SOURCE")
    symbol = doc["symbol"]
    if not (isinstance(symbol, str) and len(symbol) == 9
            and symbol[:6].isascii() and symbol[:6].isdigit()
            and symbol[6:] in (".SH", ".SZ", ".BJ")):
        raise FixtureError("INVALID_SYMBOL")
    tf = doc["timeframe"]
    if not isinstance(tf, str) or tf not in ALLOWED_TIMEFRAMES:
        raise FixtureError("INVALID_TIMEFRAME")
    if (doc["timestamp_semantic"] != "BAR_END"
            or doc["adjustment"] != "NONE"
            or doc["volume_unit"] != "SHARES"):
        raise FixtureError("UNQUALIFIED_UNIT_OR_TIMESTAMP")
    rows = doc["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise FixtureError("INVALID_ROW_COUNT")
    normalized = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != BAR_KEYS:
            raise FixtureError("INVALID_BAR_SCHEMA")
        stamp = _parse_bar_end(row["bar_end_utc"], tf)
        if stamp in normalized:
            raise FixtureError("DUPLICATE_BAR_END")
        if not all(_finite_number(row[k], positive=(k != "volume")) for k in FIELDS):
            raise FixtureError("INVALID_OHLCV")
        if not (row["low"] <= min(row["open"], row["close"])
                <= max(row["open"], row["close"]) <= row["high"]):
            raise FixtureError("INVALID_OHLC")
        normalized[stamp] = {k: float(row[k]) for k in FIELDS}
    if list(normalized) != sorted(normalized):
        raise FixtureError("UNSORTED_BAR_END")
    return {
        "source": doc["source"], "origin": doc["fixture_origin"],
        "symbol": symbol, "timeframe": tf, "rows": normalized,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def compare_files(tickflow_path: str, reference_path: str, *,
                  price_abs_tol: float = 0.001,
                  price_rel_tol: float = 0.0001,
                  volume_rel_tol: float = 0.01,
                  min_overlap: int = 10) -> dict:
    """No external calls; emit aggregate counts and provenance only."""
    safety = {
        "schema": "stock_razor_tickflow_offline_crosscheck_v0_1",
        "research_only": True, "provider_requests": 0,
        "data_qualification": "NOT_VERIFIED",
        "bar_closure_qualification": "NOT_VERIFIED",
        "trading_calendar_qualification": "NOT_VERIFIED",
        "continuity_qualification": "NOT_VERIFIED",
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED", "live_trade": False,
        "canonical_write": False,\n        "provenance_verified": False,\n        "fixture_origin_self_declared": True,
    }
    if (not all(_finite_number(x) for x in
                (price_abs_tol, price_rel_tol, volume_rel_tol))
            or type(min_overlap) is not int or not 2 <= min_overlap <= MAX_ROWS):
        return {**safety, "status": "INVALID_ARGUMENT", "ok": False}
    try:
        tick = _read_fixture(tickflow_path)
        ref = _read_fixture(reference_path)
    except FixtureError as exc:
        return {**safety, "status": "BLOCKED", "ok": False, "reason": str(exc)}
    if (tick["source"] != "TICKFLOW" or ref["source"] not in ("EASTMONEY", "TENCENT")
            or tick["symbol"] != ref["symbol"]
            or tick["timeframe"] != ref["timeframe"]):
        return {**safety, "status": "BLOCKED", "ok": False,
                "reason": "SOURCE_OR_SYMBOL_TIMEFRAME_MISMATCH"}
    a, b = tick["rows"], ref["rows"]
    common = sorted(a.keys() & b.keys())
    missing_tick = len(b.keys() - a.keys())
    missing_ref = len(a.keys() - b.keys())
    differences = {field: 0 for field in FIELDS}
    for stamp in common:
        for field in FIELDS:
            av, bv = a[stamp][field], b[stamp][field]
            abs_tol = price_abs_tol if field != "volume" else 1.0
            rel_tol = price_rel_tol if field != "volume" else volume_rel_tol
            if not math.isclose(av, bv, abs_tol=abs_tol, rel_tol=rel_tol):
                differences[field] += 1
    all_real = tick["origin"] == ref["origin"] == "REAL_CAPTURED"
    agreement = (len(common) >= min_overlap and missing_tick == missing_ref == 0
                 and not any(differences.values()))
    status = (
        "INSUFFICIENT_OVERLAP" if len(common) < min_overlap else
        "MISMATCH" if not agreement else
        "MATCH_OBSERVATIONAL" if all_real else "SYNTHETIC_TEST_ONLY"
    )
    return {
        **safety, "ok": agreement and all_real, "status": status,
        "symbol": tick["symbol"], "timeframe": tick["timeframe"],
        "tickflow_sha256": tick["sha256"], "reference_sha256": ref["sha256"],
        "reference_source": ref["source"],
        "fixture_origin": "REAL_CAPTURED" if all_real else "SYNTHETIC_OR_MIXED",\n        "comparison_agreement": agreement,
        "tickflow_rows": len(a), "reference_rows": len(b),
        "aligned_bars": len(common),
        "missing_in_tickflow": missing_tick, "missing_in_reference": missing_ref,
        "mismatch_counts": differences,
        "price_abs_tolerance": price_abs_tol,
        "price_rel_tolerance": price_rel_tol,
        "volume_rel_tolerance": volume_rel_tol,
        "min_overlap": min_overlap,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline, no-provider TickFlow bar crosscheck")
    parser.add_argument("--tickflow-fixture", required=True)
    parser.add_argument("--reference-fixture", required=True)
    parser.add_argument("--min-overlap", type=int, default=10)
    args = parser.parse_args()
    result = compare_files(args.tickflow_fixture, args.reference_fixture,
                           min_overlap=args.min_overlap)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
