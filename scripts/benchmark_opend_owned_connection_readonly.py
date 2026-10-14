#!/usr/bin/env python3
"""OpenD native K-lines on an isolated, quota-guarded temporary quote connection.

Does not touch the persistent production LiveFeed's subscription state.
The temporary quote context automatically releases its own subscription after close
(provider may retain quota for a short grace period). No historical quota/order calls.
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from math import isfinite
from time import perf_counter, sleep
import json
import os

CODES = ("US.AMD", "US.QQQ")
LIMITS = (1, 100, 500, 1000, 1001, 2000)
REPEATS = 15
MIN_REMAIN = 4  # two ephemeral 1m subscriptions + >= 2 headroom
MAX_CALLS = 30


def percentile(values, p):
    if not values:
        return None
    arr = sorted(values)
    k = (len(arr)-1)*p/100
    lo = int(k)
    hi = min(len(arr)-1,lo+1)
    return round(arr[lo] + (arr[hi]-arr[lo])*(k-lo), 2)


def safe_bars(data):
    if not hasattr(data, "to_dict"):
        return {"status":"INVALID_DATA"}
    rows = data.to_dict(orient="records")
    if not isinstance(rows,list) or not rows:
        return {"status":"EMPTY_DATA","rows":0}
    last = None
    duplicates = out_of_order = bad = 0
    for row in rows:
        ts = row.get("time_key")
        if not isinstance(ts,str) or not ts:
            bad += 1
        elif last is not None:
            if ts == last:
                duplicates += 1
            elif ts < last:
                out_of_order += 1
        if isinstance(ts,str):
            last = ts
        vv = tuple(row.get(k) for k in ("open","high","low","close","volume"))
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) for v in vv):
            bad += 1
            continue
        op,hi,lo,cl,vol = vv
        if min(op,hi,lo,cl) <= 0 or vol < 0 or hi < max(op,cl,lo)-1e-5 or lo > min(op,cl,hi)+1e-5:
            bad += 1
    return {"status":"PASS" if not (duplicates or out_of_order or bad) else "QUALITY_BLOCKED",
            "rows":len(rows),"duplicate_rows":duplicates,"out_of_order_rows":out_of_order,
            "bad_ohlcv_rows":bad}


def main():
    started = perf_counter()
    data = {"schema":"stock_razor_opend_temporary_owned_kline_benchmark_v1",
            "observed_utc":datetime.now(timezone.utc).isoformat(),
            "provider":"FUTU_OPEND_GET_CUR_KLINE", "status":"BLOCKED",
            "mode":"EPHEMERAL_OWNED_CONNECTION", "requested_symbols":list(CODES),
            "requested_periods":["1m"], "max_native_calls":MAX_CALLS,
            "production_subscription_mutations":0,
            "temporary_subscriptions_established":0,
            "explicit_history_requests":0, "trade_requests":0,
            "source_arbiter_admission":"BLOCKED", "radar_admission":"BLOCKED",
            "live_trade":False,"records":[]}
    ctx = None
    import futu as ft
    with open(os.devnull,"w",encoding="utf8") as null:
        try:
            with redirect_stdout(null),redirect_stderr(null):
                ctx = ft.OpenQuoteContext(host="127.0.0.1",port=11111)
                a, all_sub = ctx.query_subscription(is_all_conn=True)
                b, own_sub = ctx.query_subscription(is_all_conn=False)
            if a != ft.RET_OK or b != ft.RET_OK or not isinstance(all_sub,dict) or not isinstance(own_sub,dict):
                data["reason"]="SUBSCRIPTION_DISCOVERY_FAILED"
                return data
            remain = all_sub.get("remain")
            own_used = own_sub.get("own_used")
            data["preflight_remain"] = remain if type(remain) is int else None
            data["own_used_at_start"] = own_used if type(own_used) is int else None
            if type(remain) is not int or remain < MIN_REMAIN or own_used != 0:
                data["reason"]="QUOTA_HEADROOM_OR_OWN_CONTEXT_INVALID"
                return data
            with redirect_stdout(null),redirect_stderr(null):
                r, _ = ctx.subscribe(list(CODES),[ft.SubType.K_1M],
                                     is_first_push=False,subscribe_push=False)
            if r != ft.RET_OK:
                data["reason"]="TEMPORARY_SUBSCRIBE_REJECTED"
                return data
            data["temporary_subscriptions_established"]=2
            with redirect_stdout(null),redirect_stderr(null):
                q, now_owned = ctx.query_subscription(is_all_conn=False)
            owned = now_owned.get("sub_list",{}).get(ft.SubType.K_1M,[]) if q==ft.RET_OK and isinstance(now_owned,dict) else []
            if not all(s in owned for s in CODES):
                data["reason"]="OWN_CONNECTION_SUBSCRIPTION_NOT_CONFIRMED"
                return data
            timings = []; repeats = []; sent = 0
            for symbol in CODES:
                for n in LIMITS:
                    if sent >= MAX_CALLS or perf_counter()-started > 110:
                        break
                    t = perf_counter()
                    with redirect_stdout(null),redirect_stderr(null):
                        code, payload = ctx.get_cur_kline(symbol,n,ktype=ft.KLType.K_1M,
                                                          autype=ft.AuType.NONE)
                    ms = round((perf_counter()-t)*1000,2)
                    sent += 1
                    if code != ft.RET_OK:
                        record = {"symbol":symbol,"count":n,"status":"PROVIDER_REJECTED","native_ms":ms}
                    else:
                        quality = safe_bars(payload)
                        record = {"symbol":symbol,"count":n,"native_ms":ms,**quality}
                        if quality["status"]=="PASS":
                            timings.append(ms)
                    data["records"].append(record)
                    sleep(.08)
            for _ in range(REPEATS):
                if sent >= MAX_CALLS or perf_counter()-started > 110:
                    break
                t=perf_counter()
                with redirect_stdout(null),redirect_stderr(null):
                    ret,payload=ctx.get_cur_kline(CODES[0],100,ktype=ft.KLType.K_1M,
                                                  autype=ft.AuType.NONE)
                ms=round((perf_counter()-t)*1000,2)
                sent += 1
                if ret==ft.RET_OK and safe_bars(payload)["status"]=="PASS":
                    repeats.append(ms)
                sleep(.08)
            data.update({
                "status":"PASS_NATIVE" if timings else "BLOCKED_NO_VALID_NATIVE_KLINES",
                "call_count":sent,"valid_depth_calls":len(timings),
                "depth_p50_ms":percentile(timings,50),"depth_p95_ms":percentile(timings,95),
                "repeat_valid":len(repeats),"repeat_p50_ms":percentile(repeats,50),
                "repeat_p95_ms":percentile(repeats,95),
                "requested_over_provider_cap":[1001,2000],
                "analysis_performed":False,
                "elapsed_s":round(perf_counter()-started,2),
            })
            return data
        except Exception as exc:
            data["reason"]="EXCEPTION"
            data["exception_class"]=type(exc).__name__
            return data
        finally:
            if ctx is not None:
                try:
                    with redirect_stdout(null),redirect_stderr(null):
                        ctx.close()
                    data["temporary_context_closed"]=True
                except Exception:
                    data["temporary_context_closed"]=False


if __name__=="__main__":
    print(json.dumps(main(),separators=(",",":"),sort_keys=True))
