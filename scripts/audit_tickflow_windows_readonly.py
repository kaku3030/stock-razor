"""Bounded Windows TickFlow K-line qualification; absolutely no trading/writes.

Official TickFlow 0.1.25 REST only; secure user Windows Credential Manager.
Only fixed ETFs and 15m/60m/1d. Reports enums/counts/latencies, never key,
quotes, raw provider rows, exact OHLC, account info, or exception messages.

Run explicitly: python scripts/audit_tickflow_windows_readonly.py --execute
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import importlib.metadata
import json
import math
import re
import time
from zoneinfo import ZoneInfo

SYMBOLS = ("159611.SZ", "518880.SH")
PERIOD_COUNTS = {"15m": 96, "60m": 24, "1d": 40}
END_CLOCKS = {
    "15m": ("09:45", "10:00", "10:15", "10:30", "10:45", "11:00",
            "11:15", "11:30", "13:15", "13:30", "13:45", "14:00",
            "14:15", "14:30", "14:45", "15:00"),
    "60m": ("10:30", "11:30", "14:00", "15:00"),
}
CN = ZoneInfo("Asia/Shanghai")
CRED_TARGET = "StockRazor/TickFlow/APIKey"


def read_windows_credential() -> str:
    """Return a key to the caller in memory only, never on argv/logs/disk."""
    import win32cred  # type: ignore[import-not-found]  # optional Windows dependency

    record = win32cred.CredRead(CRED_TARGET, win32cred.CRED_TYPE_GENERIC)
    blob = record.get("CredentialBlob")
    if isinstance(blob, bytes):
        key = blob.decode("utf-16-le") if bytes((0,)) in blob else blob.decode("utf-8")
    elif isinstance(blob, str):
        key = blob
    else:
        raise ValueError("credential unavailable")
    if not key.strip():
        raise ValueError("credential unavailable")
    return key.strip()


def safe_error_type(error: Exception) -> str:
    name = type(error).__name__
    # User/plugin exception bodies are untrusted; only the class name is safe.
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", name) else "OtherError"


def assess_compact(frame: object, timeframe: str, now_utc: datetime) -> dict:
    """Validate chronological compact SDK columns, never return market values."""
    if timeframe not in PERIOD_COUNTS or now_utc.tzinfo is None:
        raise ValueError("invalid period/clock")
    keys = ("timestamp", "open", "high", "low", "close", "volume")
    if not isinstance(frame, dict) or any(
        not isinstance(frame.get(key), (list, tuple)) for key in keys
    ):
        raise ValueError("compact column shape invalid")
    sizes = {len(frame[key]) for key in keys}
    if len(sizes) != 1:
        raise ValueError("compact column lengths mismatch")
    count = sizes.pop()
    if not 4 <= count <= PERIOD_COUNTS[timeframe]:
        raise ValueError("out-of-bounds sample size")

    now_cn = now_utc.astimezone(CN)
    cutoff = now_cn - timedelta(seconds=90)
    due = set()
    if timeframe in END_CLOCKS and now_cn.weekday() < 5:
        due = {
            now_cn.replace(hour=int(h[:2]), minute=int(h[3:]),
                           second=0, microsecond=0)
            for h in END_CLOCKS[timeframe]
        }
        due = {stamp for stamp in due if stamp <= cutoff}

    previous = None
    eligible = set()
    future_or_forming = 0
    invalid_ohlc = 0
    duplicate_or_reordered = 0
    same_day_daily_quarantined = 0
    latest_prior_daily_seen = False
    for i in range(count):
        try:
            epoch = float(frame["timestamp"][i])
            if not math.isfinite(epoch):
                raise ValueError("nonfinite timestamp")
            if epoch > 1e12:
                epoch /= 1000
            stamp = datetime.fromtimestamp(epoch, timezone.utc).astimezone(CN)
            nums = [float(frame[k][i]) for k in keys[1:]]
            if (not all(math.isfinite(x) for x in nums)
                or min(nums[:4]) <= 0 or nums[4] < 0
                or nums[1] + 0.00001 < max(nums[0], nums[2], nums[3])
                or nums[2] - 0.00001 > min(nums[0], nums[1], nums[3])):
                invalid_ohlc += 1
                continue
            if previous is not None and stamp <= previous:
                duplicate_or_reordered += 1
            previous = stamp
            if timeframe == "1d":
                if stamp.date() >= now_cn.date():
                    same_day_daily_quarantined += 1
                else:
                    latest_prior_daily_seen = True
                continue
            if stamp > cutoff:
                future_or_forming += 1
                continue
            if stamp.date() == now_cn.date():
                eligible.add(stamp)
        except (TypeError, ValueError, KeyError, IndexError, OverflowError, OSError):
            invalid_ohlc += 1

    if timeframe == "1d":
        status = (
            "PASS_PRIOR_DAILY_RESEARCH_ONLY"
            if latest_prior_daily_seen and not invalid_ohlc and not duplicate_or_reordered
            else "BLOCKED"
        )
        return {
            "status": status, "returned_rows": count,
            "same_day_daily_quarantined": same_day_daily_quarantined,
            "invalid_rows": invalid_ohlc,
            "reordered_or_duplicate_rows": duplicate_or_reordered,
            "current_day_d1_finality": "NOT_VERIFIED",
        }

    missing = len(due - eligible)
    status = (
        "PASS_RESEARCH_ONLY"
        if not missing and not invalid_ohlc and not duplicate_or_reordered
        else "BLOCKED_UNVERIFIED"
    )
    return {
        "status": status, "returned_rows": count,
        "due_count": len(due), "due_labels_present": len(due & eligible),
        "due_labels_missing": missing, "future_or_forming_quarantined": future_or_forming,
        "invalid_rows": invalid_ohlc,
        "reordered_or_duplicate_rows": duplicate_or_reordered,
        "exchange_bar_finality": "NOT_VERIFIED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Opt in to <=6 paid REST reads")
    parser.add_argument("--timeframe", choices=("15m", "60m", "1d", "all"), default="all")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({
            "status": "NOT_EXECUTED_OPT_IN_REQUIRED",
            "symbols": list(SYMBOLS), "timeframe": args.timeframe,
            "provider_requests": 0, "trading_admission": "BLOCKED",
        }, sort_keys=True))
        return 0

    try:
        version = importlib.metadata.version("tickflow")
        if version != "0.1.25":
            raise RuntimeError("pinned SDK version mismatch")
        from tickflow import TickFlow
        key = read_windows_credential()
        client = TickFlow(api_key=key, timeout=8.0, max_retries=0)
        del key
    except Exception as exc:
        print(json.dumps({"status": "CREDENTIAL_OR_SDK_BLOCKED",
                          "error_class": safe_error_type(exc),
                          "trading_admission": "BLOCKED"}, sort_keys=True))
        return 2

    requested = tuple(PERIOD_COUNTS) if args.timeframe == "all" else (args.timeframe,)
    failed = False
    try:
        for symbol in SYMBOLS:
            for timeframe in requested:
                start = time.perf_counter()
                try:
                    frame = client.klines.get(
                        symbol, period=timeframe, count=PERIOD_COUNTS[timeframe],
                        as_dataframe=False, adjust="none",
                    )
                    record = assess_compact(frame, timeframe, datetime.now(timezone.utc))
                except Exception as exc:
                    record = {"status": "BLOCKED",
                              "error_class": safe_error_type(exc)}
                record.update({
                    "symbol": symbol, "timeframe": timeframe,
                    "request_ms": round((time.perf_counter() - start) * 1000, 2),
                    "data_source": "TICKFLOW_PREMIUM_DESKTOP_READONLY",
                    "provider_requests": 1,
                    "trading_admission": "BLOCKED", "live_trade": False,
                })
                print(json.dumps(record, sort_keys=True), flush=True)
                failed |= record["status"].startswith("BLOCKED")
    finally:
        try:
            client.close()
        except Exception:
            pass
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
