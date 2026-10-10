"""Convert a locally saved, read-only CN MCP observation into a private offline fixture.

No API/SDK/network. Explicit manual volume-unit attestation is required.
The resulting fixture remains self-declared evidence, NOT market admission.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = "stock_razor_cn_offline_bar_fixture_v0_1"
CN = ZoneInfo("Asia/Shanghai")
MAX_BYTES = 1_000_000
MAX_ROWS = 500


class ConversionError(ValueError):
    pass


def _utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ConversionError("INVALID_TIMESTAMP")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConversionError("INVALID_TIMESTAMP") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ConversionError("NAIVE_TIMESTAMP")
    return dt.astimezone(timezone.utc)


def _price(value) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ConversionError("INVALID_PRICE")
    return float(value)


def convert_cn_mcp_observation(
    observation: dict, *, symbol: str, timeframe: str,
    shares_per_hand: int | None = None, attested_volume_unit: bool = False,
    min_capture_lag_seconds: int = 60,
) -> dict:
    if not isinstance(observation, dict):
        raise ConversionError("INVALID_INPUT")
    if (not isinstance(symbol, str) or len(symbol) != 9
            or not symbol[:6].isascii() or not symbol[:6].isdigit()
            or symbol[6:] not in (".SH", ".SZ", ".BJ")):
        raise ConversionError("INVALID_SYMBOL")
    if timeframe not in ("15m", "60m"):
        raise ConversionError("INVALID_TIMEFRAME")
    if (observation.get("ok") is not True or observation.get("status") != "PASS"
            or observation.get("symbol_status") != "PASS"):
        raise ConversionError("UNQUALIFIED_MCP_OBSERVATION")
    if (observation.get("symbol") != symbol[:6]
            or observation.get("timeframe") != timeframe):
        raise ConversionError("SYMBOL_OR_TIMEFRAME_MISMATCH")
    if (observation.get("timestamp_semantic") != "BAR_END"
            or observation.get("symbol_intraday_timestamp_semantics_proven") is not True
            or not isinstance(observation.get("timestamp_qualification"), dict)
            or observation["timestamp_qualification"].get("status") != "PASS"):
        raise ConversionError("TIMESTAMP_SEMANTICS_UNPROVEN")
    provider = observation.get("provider_used")
    if provider not in ("tencent", "eastmoney"):
        raise ConversionError("UNSUPPORTED_PROVIDER")
    if not attested_volume_unit:
        raise ConversionError("VOLUME_UNIT_ATTESTATION_REQUIRED")
    if (type(min_capture_lag_seconds) is not int
            or not 60 <= min_capture_lag_seconds <= 86400):
        raise ConversionError("INVALID_CAPTURE_LAG")
    emitted = _utc(observation.get("emitted_at_utc"))
    raw_rows = observation.get("rows")
    if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= MAX_ROWS:
        raise ConversionError("INVALID_ROW_COUNT")
    output = []
    for row in raw_rows:
        if not isinstance(row, dict) or row.get("provider") != provider:
            raise ConversionError("INVALID_ROW_PROVIDER")
        if row.get("quality_flags") != []:
            raise ConversionError("ROW_QUALITY_UNVERIFIED")
        label = row.get("label")
        if not isinstance(label, str) or len(label) != 16:
            raise ConversionError("INVALID_BAR_LABEL")
        try:
            local = datetime.strptime(label, "%Y-%m-%d %H:%M").replace(tzinfo=CN)
        except ValueError as exc:
            raise ConversionError("INVALID_BAR_LABEL") from exc
        bar_end = local.astimezone(timezone.utc)
        if bar_end > emitted - timedelta(seconds=min_capture_lag_seconds):
            raise ConversionError("BAR_NOT_CLOSED_AT_CAPTURE")
        if row.get("volume_unit") == "SHARES":
            if shares_per_hand is not None:
                raise ConversionError("UNEXPECTED_VOLUME_MULTIPLIER")
            multiplier = 1
        elif row.get("volume_unit") == "HAND":
            if type(shares_per_hand) is not int or not 1 <= shares_per_hand <= 100000:
                raise ConversionError("EXPLICIT_HAND_MULTIPLIER_REQUIRED")
            multiplier = shares_per_hand
        else:
            raise ConversionError("UNSUPPORTED_VOLUME_UNIT")
        raw_volume = row.get("volume_raw")
        if (type(raw_volume) not in (int, float)
                or not math.isfinite(raw_volume) or raw_volume < 0):
            raise ConversionError("INVALID_VOLUME")
        volume = float(raw_volume) * multiplier
        if not math.isfinite(volume):
            raise ConversionError("INVALID_VOLUME")
        o, h, l, c = (_price(row.get(k)) for k in ("open", "high", "low", "close"))
        if not (l <= min(o, c) <= max(o, c) <= h):
            raise ConversionError("INVALID_OHLC")
        output.append({
            "bar_end_utc": bar_end.isoformat(), "open": o, "high": h,
            "low": l, "close": c, "volume": volume,
        })
    stamps = [r["bar_end_utc"] for r in output]
    if stamps != sorted(set(stamps)):
        raise ConversionError("UNSORTED_OR_DUPLICATE_BARS")
    return {
        "schema": SCHEMA,
        "fixture_origin": "REAL_CAPTURED",
        "source": provider.upper(),
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp_semantic": "BAR_END",
        "adjustment": "NONE",
        "volume_unit": "SHARES",
        "rows": output,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline private CN MCP fixture converter")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", choices=("15m", "60m"), required=True)
    parser.add_argument("--shares-per-hand", type=int)
    parser.add_argument("--attest-volume-unit", action="store_true")
    args = parser.parse_args()
    try:
        with open(args.input, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ConversionError("INPUT_TOO_LARGE")
        observation = json.loads(raw)
        fixture = convert_cn_mcp_observation(
            observation, symbol=args.symbol, timeframe=args.timeframe,
            shares_per_hand=args.shares_per_hand,
            attested_volume_unit=args.attest_volume_unit,
        )
        # Create a private new file; never overwrite or print bars/credentials.
        out = Path(args.output)
        if not out.parent.is_dir():
            raise ConversionError("OUTPUT_PARENT_MISSING")
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(fixture, handle, separators=(",", ":"), sort_keys=True)
        print(json.dumps({"status": "CREATED_PRIVATE_FIXTURE",
                          "rows": len(fixture["rows"]),
                          "provenance_verified": False,
                          "data_qualification": "NOT_VERIFIED",
                          "radar_admission": "BLOCKED",
                          "live_trade": False}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        reason = str(exc) if isinstance(exc, ConversionError) else "IO_OR_JSON_FAILURE"
        print(json.dumps({"status": "BLOCKED", "reason": reason,
                          "radar_admission": "BLOCKED", "live_trade": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
