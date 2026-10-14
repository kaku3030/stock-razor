"""Isolated AWS TickFlow Premium polling; absolutely no canonical/trading writes."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
import json
import os
import signal
import time

from data_provider.cn_tickflow_research_cache import (
    SYMBOLS, DEFAULT_PATH, atomic_publish, build_observation,
)

SECRET_NAME="stock-razor/tickflow/premium-api-key"
running=True

# One stable failure enum per locally-defined validation error. Exact string
# matches only; never publish the raw provider error, payload or credential.
_NORMALIZE_REJECTION_REASON = {
    "unsupported period": "UNSUPPORTED_PERIOD",
    "naive clock": "CLOCK_MISSING_TZ",
    "missing compact SDK column": "COLUMN_MISSING_OR_NOT_LIST",
    "compact SDK column lengths differ": "COLUMN_LENGTH_MISMATCH",
    "insufficient or unbounded history": "ROW_COUNT_OUT_OF_BOUNDS",
    "unexpected SDK data type": "SDK_SHAPE_INVALID",
    "non-dict record": "ROW_TYPE_INVALID",
    "invalid provider timestamp": "TIMESTAMP_TYPE_INVALID",
    "provider epoch outside bounded range": "TIMESTAMP_EPOCH_INVALID",
    "no provider timestamp": "TIMESTAMP_MISSING",
    "reordered/duplicate timestamp": "TIMESTAMP_ORDER_INVALID",
    "unexpected Shanghai regular-session grid": "HISTORICAL_SESSION_GRID_MISMATCH",
    "future trading date": "FUTURE_TRADING_DATE",
    "invalid provider number": "OHLCVA_NUMBER_TYPE_INVALID",
    "missing provider column": "OHLCVA_COLUMN_MISSING",
    "invalid OHLCVA": "OHLCVA_RELATION_INVALID",
    "invalid OHLCVA nonpositive": "OHLCVA_NONPOSITIVE",
    "invalid OHLCVA high below body": "OHLCVA_HIGH_LT_BODY",
    "invalid OHLCVA low above body": "OHLCVA_LOW_GT_BODY",
    "invalid OHLCVA negative volume": "OHLCVA_VOLUME_NEGATIVE",
    "invalid OHLCVA negative amount": "OHLCVA_AMOUNT_NEGATIVE",
    "no sufficient historical closed-time candidates": "VALID_BAR_COUNT_LOW",
    "invalid supplemental timeframe flag": "INVALID_EXTRA_PERIODS",
}

def _normalize_rejection_reason(error: Exception) -> str:
    stage=getattr(error, "_tickflow_stage", "")
    if (type(error) is ValueError and isinstance(stage,str)
            and stage.endswith("_NORMALIZE")):
        return _NORMALIZE_REJECTION_REASON.get(str(error), "OTHER")
    return "NOT_APPLICABLE"



def _ohlc_float_gap_bucket(error: Exception) -> str:
    """Only a fixed enum for historical OHLC rejection, never provider data."""
    stage=getattr(error,"_tickflow_stage","")
    value=getattr(error,"_tickflow_ohlc_float_gap_bucket","UNKNOWN")
    if (type(error) is ValueError and isinstance(stage,str)
            and stage.endswith("_NORMALIZE")
            and value in ("WITHIN_1E_MINUS_5","OVER_1E_MINUS_5")):
        return value
    return "UNKNOWN"


def _stop(*_args):
    global running
    running=False

def _credential():
    # AWS instance IAM -> Secrets Manager; key never emitted nor written.
    import boto3
    text=boto3.client("secretsmanager",region_name="ap-northeast-1").get_secret_value(
        SecretId=SECRET_NAME)["SecretString"]
    payload=json.loads(text)
    if not isinstance(payload,dict) or set(payload)!={"api_key"}:
        raise ValueError("invalid secret contract")
    value=payload["api_key"]
    if not isinstance(value,str) or not value.strip():
        raise ValueError("invalid credential")
    return value

def _interval(now: datetime, failure: bool=False) -> int:
    sh=now.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
    if sh.weekday()>=5:
        return 900
    hhmm=sh.hour*60+sh.minute
    session=(570 <= hhmm <= 690) or (780 <= hhmm <= 900)
    # Read-only REST, 8 bounded Kline requests per cadence, not ticks.
    return 300 if failure or not session else 60

def main() -> int:
    sha=os.environ.get("STOCK_RAZOR_REPO_SHA","")
    if not __import__("re").fullmatch("[0-9a-f]{40}",sha):
        return 2
    status_path=os.environ.get("STOCK_RAZOR_CN_TICKFLOW_STATUS_PATH",DEFAULT_PATH)
    if Path(status_path).resolve()!=Path(DEFAULT_PATH).resolve():
        # Avoid allowing a misconfigured env to overwrite another service.
        return 2
    signal.signal(signal.SIGTERM,_stop)
    signal.signal(signal.SIGINT,_stop)
    # Init SDK with AWS IAM key in process memory, never argv or systemd env.
    try:
        with open(os.devnull,"w",encoding="utf-8") as null:
            with redirect_stdout(null), redirect_stderr(null):
                api_key=_credential()
                from tickflow import TickFlow
                # Do not magnify a 4-request sample into hidden SDK retries
                # under throttling or expired subscriptions.
                client=TickFlow(api_key=api_key,timeout=8.0,max_retries=0)
            del api_key
    except Exception as exc:
        print("TICKFLOW_RESEARCH_BOOT=BLOCKED:"+type(exc).__name__,flush=True)
        return 3
    sequence=0
    try:
        while running:
            sequence+=1
            now=datetime.now(timezone.utc)
            failed=False
            try:
                with open(os.devnull,"w",encoding="utf-8") as null:
                    with redirect_stdout(null), redirect_stderr(null):
                        snapshot=build_observation(client,now_utc=now,repo_sha=sha,
                              sequence=sequence,symbols=SYMBOLS,include_supplemental=True)
                atomic_publish(status_path,snapshot)
                print("TICKFLOW_RESEARCH_POLL=RESEARCH_ONLY_PASS",flush=True)
            except Exception as exc:
                failed=True
                # Invalid/late feed must replace an older apparently fresh file.
                atomic_publish(status_path,{
                    "schema":"stock_razor_cn_tickflow_research_observation_v0_1",
                    "provider":"TICKFLOW_PREMIUM","repo_sha":sha,
                    "observed_at_utc":datetime.now(timezone.utc).isoformat(),
                    "sequence":sequence,"status":"BLOCKED",
                    "failure_class":type(exc).__name__,
                    "failure_reason":_normalize_rejection_reason(exc),
                    "failure_ohlc_float_gap_bucket":_ohlc_float_gap_bucket(exc),
                    "failure_stage":(
                        getattr(exc,"_tickflow_stage","UNKNOWN")
                        if getattr(exc,"_tickflow_stage","UNKNOWN") in {
                            "S0_15M_FETCH","S0_15M_NORMALIZE",
                            "S0_60M_FETCH","S0_60M_NORMALIZE",
                            "S1_15M_FETCH","S1_15M_NORMALIZE",
                            "S1_60M_FETCH","S1_60M_NORMALIZE",
                            "S0_5M_FETCH","S0_5M_NORMALIZE",
                            "S1_5M_FETCH","S1_5M_NORMALIZE",
                            "S0_1D_FETCH","S0_1D_NORMALIZE",
                            "S1_1D_FETCH","S1_1D_NORMALIZE",
                        } else "UNKNOWN"
                    ),
                    "symbols":{},"research_only":True,
                    "provider_first_target":True,
                    "source_arbiter_admission":"BLOCKED",
                    "radar_admission":"BLOCKED","live_trade":False,
                    "can_confirm_signal":False,"canonical_write_authorized":False,
                })
                print("TICKFLOW_RESEARCH_POLL=BLOCKED:"+type(exc).__name__,flush=True)
            pause=_interval(datetime.now(timezone.utc),failure=failed)
            # Interruptible shutdown, no runaway provider retry loop.
            for _ in range(pause):
                if not running: break
                time.sleep(1)
    finally:
        try:
            with open(os.devnull,"w",encoding="utf-8") as null:
                with redirect_stdout(null),redirect_stderr(null):
                    client.close()
        except Exception:
            pass
    return 0

if __name__=="__main__":
    raise SystemExit(main())

