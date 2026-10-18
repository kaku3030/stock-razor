#!/usr/bin/env python3
"""Read-only AWS OpenD native K-line depth/latency qualification; no subscriptions.

Requires existing K-line entitlement and subscriptions owned by this connection.
Subscriptions discovered on another connection cannot qualify this caller.
Never calls subscribe/unsubscribe, history quotas, market orders or any setters.
Prints only allowlisted aggregate measurements (no provider prices or errors).
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from math import isfinite
from statistics import median
from time import perf_counter, sleep
import json
import os

SYMBOLS = ("US.AMD", "US.QQQ")
PERIODS = ("1m", "5m", "15m", "60m")
COUNTS = (1, 100, 500, 1000, 1001, 2000)
REPEATS = 12
MAX_CALLS = 65
MAX_ELAPSED_S = 140


def percentile(seq, q):
    if not seq:
        return None
    arr = sorted(seq)
    pos = (len(arr)-1)*q/100
    index = int(pos)
    after = min(index+1, len(arr)-1)
    return round(arr[index] + (arr[after]-arr[index])*(pos-index), 2)


def quality_check(payload):
    if not hasattr(payload, "to_dict"):
        return {"returned": 0, "integrity": "UNRECOGNIZED_SCHEMA"}
    try:
        rows = payload.to_dict(orient="records")
    except (TypeError, ValueError, KeyError):
        return {"returned": 0, "integrity": "UNRECOGNIZED_SCHEMA"}
    if not isinstance(rows, list):
        return {"returned": 0, "integrity": "UNRECOGNIZED_SCHEMA"}
    duplicates = 0
    out_of_order = 0
    malformed = 0
    previous = None
    for row in rows:
        stamp = row.get("time_key")
        if not isinstance(stamp, str) or not stamp:
            malformed += 1
        elif previous is not None:
            if stamp == previous:
                duplicates += 1
            elif stamp < previous:
                out_of_order += 1
        if isinstance(stamp, str):
            previous = stamp
        numbers = tuple(row.get(k) for k in ("open", "high", "low", "close", "volume"))
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not isfinite(v) for v in numbers):
            malformed += 1
            continue
        op, hi, lo, cl, volume = numbers
        if (hi < max(op, cl, lo) - 0.00001 or
                lo > min(op, cl, hi) + 0.00001 or
                volume < 0 or min(op, hi, lo, cl) <= 0):
            malformed += 1
    return {
        "returned": len(rows),
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "malformed": malformed,
        "integrity": (
            "PASS" if rows and not (duplicates or out_of_order or malformed)
            else "BLOCKED"
        ),
    }


def main():
    started = perf_counter()
    result = {
        "schema": "stock_razor_opend_native_kline_bounded_benchmark_v1",
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "source": "FUTU_OPEND_NATIVE_GET_CUR_KLINE",
        "market": "US",
        "subscription_changes": 0,
        "historical_quota_consumed_by_explicit_history_api": 0,
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "max_calls": MAX_CALLS,
        "results": [],
        "connection": "NOT_VERIFIED",
        "subscription_scope": "CURRENT_CONNECTION",
        "status": "BLOCKED",
        "call_count": 0,
    }
    ctx = None
    import futu as ft
    import sys
    with open(os.devnull, "w", encoding="utf8") as sink:
        try:
            with redirect_stdout(sink), redirect_stderr(sink):
                ctx = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
                ret, subscriptions = ctx.query_subscription(is_all_conn=False)
            result["connection"] = "PASS"
            if ret != ft.RET_OK or not isinstance(subscriptions, dict):
                result["subscription_discovery"] = "BLOCKED"
                return result
            subs = subscriptions.get("sub_list")
            if not isinstance(subs, dict):
                result["subscription_discovery"] = "UNKNOWN"
                return result
            selected = []
            for label, ktype, stype in (
                ("1m", ft.KLType.K_1M, ft.SubType.K_1M),
                ("5m", ft.KLType.K_5M, ft.SubType.K_5M),
                ("15m", ft.KLType.K_15M, ft.SubType.K_15M),
                ("60m", ft.KLType.K_60M, ft.SubType.K_60M),
            ):
                members = subs.get(stype)
                if not isinstance(members, (list, tuple, set)):
                    continue
                for symbol in SYMBOLS:
                    if symbol in members:
                        selected.append((symbol, label, ktype))
            result["subscription_discovery"] = "PASS"
            result["preexisting_symbol_timeframe_pairs"] = len(selected)
            result["preexisting_codes"] = sorted({s for s, _, _ in selected})
            result["preexisting_periods"] = sorted({t for _, t, _ in selected})
            if not selected:
                result["status"] = "BLOCKED_NO_PREEXISTING_KLINE_SUBSCRIPTION"
                return result
            elapsed_requests = []
            request_calls = 0
            for symbol, label, ktype in selected:
                for count in COUNTS:
                    if request_calls >= MAX_CALLS or perf_counter() - started > MAX_ELAPSED_S:
                        break
                    t = perf_counter()
                    try:
                        with redirect_stdout(sink), redirect_stderr(sink):
                            code, payload = ctx.get_cur_kline(
                                symbol, count, ktype=ktype, autype=ft.AuType.NONE
                            )
                        ms = round((perf_counter()-t)*1000, 2)
                        if code != ft.RET_OK:
                            record = {"symbol": symbol, "period": label, "requested": count,
                                      "status": "PROVIDER_REJECTED", "native_elapsed_ms": ms}
                        else:
                            checked = quality_check(payload)
                            record = {"symbol": symbol, "period": label, "requested": count,
                                      "status": checked["integrity"], "native_elapsed_ms": ms,
                                      **checked}
                            if checked["integrity"] == "PASS":
                                elapsed_requests.append(ms)
                    except Exception as error:
                        record = {"symbol": symbol, "period": label, "requested": count,
                                  "status": "ERROR", "failure_class": type(error).__name__,
                                  "native_elapsed_ms": round((perf_counter()-t)*1000, 2)}
                    result["results"].append(record)
                    request_calls += 1
                    if record["status"] != "PASS":
                        break
                    sleep(0.08)
            # Repeat a bounded warm-connection query: no new subscription.
            repeat_timing = []
            first = selected[0]
            for _ in range(REPEATS):
                if request_calls >= MAX_CALLS or perf_counter() - started > MAX_ELAPSED_S:
                    break
                t = perf_counter()
                try:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        code, payload = ctx.get_cur_kline(
                            first[0], 100, ktype=first[2], autype=ft.AuType.NONE
                        )
                    ms = round((perf_counter()-t)*1000, 2)
                    if code == ft.RET_OK and quality_check(payload)["integrity"] == "PASS":
                        repeat_timing.append(ms)
                    else:
                        result["repeated_failures"] = result.get("repeated_failures", 0) + 1
                except Exception:
                    result["repeated_failures"] = result.get("repeated_failures", 0) + 1
                request_calls += 1
                sleep(0.08)
            result["call_count"] = request_calls
            result["native_p50_ms"] = percentile(elapsed_requests, 50)
            result["native_p95_ms"] = percentile(elapsed_requests, 95)
            result["repeat_p50_ms"] = percentile(repeat_timing, 50)
            result["repeat_p95_ms"] = percentile(repeat_timing, 95)
            result["repeated_passes"] = len(repeat_timing)
            result["errors"] = sum(x["status"] == "ERROR" for x in result["results"])
            result["provider_rejected"] = sum(
                x["status"] == "PROVIDER_REJECTED" for x in result["results"]
            )
            result["quality_blocked"] = sum(
                x["status"] == "BLOCKED" for x in result["results"]
            )
            result["status"] = "TESTED_READONLY"
            result["total_elapsed_s"] = round(perf_counter() - started, 2)
        except Exception as error:
            result["status"] = "BLOCKED"
            result["failure_class"] = type(error).__name__
        finally:
            if ctx is not None:
                try:
                    with redirect_stdout(sink), redirect_stderr(sink):
                        ctx.close()
                except Exception:
                    pass
    return result


if __name__ == "__main__":
    print(json.dumps(main(), separators=(",", ":"), sort_keys=True))
