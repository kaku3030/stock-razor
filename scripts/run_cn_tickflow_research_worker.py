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
    SYMBOLS, DEFAULT_PATH, atomic_publish, build_observation, resolve_scan_symbols,
)
from data_provider.tickflow_ws_research_observer import attach_tickflow_stream
from data_provider.tickflow_evidence_checkpoints import record_postclose_checkpoint, SAFE as EVIDENCE_SAFE

SECRET_NAME="stock-razor/tickflow/premium-api-key"
running=True


def _postclose_evidence(snapshot, now):
    # Evidence failure is independently visible; never discard valid research
    # prices or promote any gate because a private checkpoint could not save.
    try:
        return record_postclose_checkpoint(snapshot, now_utc=now)
    except OSError:
        return {**EVIDENCE_SAFE, "status":"EVIDENCE_IO_BLOCKED"}
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**EVIDENCE_SAFE, "status":"EVIDENCE_VALIDATION_BLOCKED"}
    except Exception:
        return {**EVIDENCE_SAFE, "status":"EVIDENCE_INTERNAL_BLOCKED"}

# One stable failure enum per locally-defined validation error. Exact string
# matches only; never publish the raw provider error, payload or credential.
_NORMALIZE_REJECTION_REASON = {
    "unsupported period": "UNSUPPORTED_PERIOD",
    "naive clock": "CLOCK_MISSING_TZ",
    "missing compact SDK column": "COLUMN_MISSING_OR_NOT_LIST",
    "compact SDK column lengths differ": "COLUMN_LENGTH_MISMATCH",
    "insufficient or unbounded history": "ROW_COUNT_OUT_OF_BOUNDS",
    "insufficient history": "ROW_COUNT_BELOW_MIN",
    "history exceeds configured bound": "ROW_COUNT_ABOVE_MAX",
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
    if stage in {
            f"BATCH_{period}_{route}_FALLBACK"
            for period in ("1M", "5M", "15M", "60M", "1D")
            for route in ("SYMBOL", "HISTORY", "INTRADAY")}:
        return "BATCH_SYMBOL_FALLBACK_FAILED"
    if type(error) is ValueError and stage in {
            f"BATCH_{period}_{route}_FETCH"
            for period in ("1M", "5M", "15M", "60M", "1D")
            for route in ("FETCH", "HISTORY", "INTRADAY")}:
        return {
            "batch SDK shape invalid": "BATCH_SHAPE_INVALID",
            "batch SDK symbol missing": "BATCH_SYMBOL_MISSING",
        }.get(str(error), "NOT_APPLICABLE")
    if (type(error) is ValueError and stage == "S4_CACHE_PUBLISH"
            and str(error) == "private research cache exceeds bounded bytes"):
        return "CACHE_SIZE_EXCEEDED"
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
    # Read-only REST, bounded Kline requests per cadence, not ticks. The
    # default remains the four held ETFs; explicit phase scans are capped by
    # resolve_scan_symbols.
    return 300 if failure or not session else 15

def _network_retry_interval(now: datetime, error: Exception | None, failures: int) -> int:
    """Bounded polling recovery, never hidden SDK retries or auth retries.

    The default four-symbol cycle is bounded and >=15s between cycles retain a
    single worker. Repeated network failures
    back off to the original 300s; weekends retain 900s.
    """
    conservative = _interval(now, failure=True)
    # SDK versions may wrap transport errors in their own exception classes.
    # Match fixed names only; do not inspect or log their private messages.
    transient = type(error).__name__ in {
        "TimeoutError", "ConnectTimeout", "ReadTimeout", "WriteTimeout",
        "PoolTimeout", "ConnectionError", "ConnectError", "ReadError",
        "RemoteProtocolError",
    }
    if not transient or conservative == 900:
        return conservative
    return min(300, 15 * (2 ** min(max(failures - 1, 0), 5)))


def _websocket_enabled() -> bool:
    return os.environ.get("TICKFLOW_RESEARCH_WS_ENABLED", "false").strip().lower() in {
        "1", "true", "yes",
    }


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
    try:
        scan_symbols=resolve_scan_symbols(os.environ.get("TICKFLOW_RESEARCH_SYMBOLS"))
    except ValueError:
        print("TICKFLOW_RESEARCH_SYMBOLS=BLOCKED:INVALID",flush=True)
        return 2
    # Init SDK with AWS IAM key in process memory, never argv or systemd env.
    try:
        with open(os.devnull,"w",encoding="utf-8") as null:
            with redirect_stdout(null), redirect_stderr(null):
                api_key=_credential()
                from tickflow import TickFlow
                # Do not magnify a 4-request sample into hidden SDK retries
                # under throttling or expired subscriptions.
                # A bounded 200-symbol cloud batch needs a longer single-call
                # envelope than the four-symbol default, while retries remain
                # disabled and the outer poll loop still backs off on failure.
                scan_timeout = 30.0 if len(scan_symbols) > len(SYMBOLS) else 8.0
                client=TickFlow(api_key=api_key,timeout=scan_timeout,max_retries=0)
            del api_key
    except Exception as exc:
        print("TICKFLOW_RESEARCH_BOOT=BLOCKED:"+type(exc).__name__,flush=True)
        return 3
    ws_observer = None
    if _websocket_enabled():
        try:
            with open(os.devnull, "w", encoding="utf-8") as null:
                with redirect_stdout(null), redirect_stderr(null):
                    # The official observer remains capped at five symbols;
                    # REST/Kline capacity is independent from this protocol
                    # evidence leg.
                    ws_observer = attach_tickflow_stream(client, scan_symbols[:5])
        except Exception as exc:
            # REST research remains independent; the optional WS leg is an
            # explicit blocked observation rather than a silent live claim.
            print("TICKFLOW_RESEARCH_WS=BLOCKED:" + type(exc).__name__, flush=True)
    sequence=0
    network_failures=0
    try:
        while running:
            sequence+=1
            now=datetime.now(timezone.utc)
            failed=False
            failure=None
            try:
                with open(os.devnull,"w",encoding="utf-8") as null:
                    with redirect_stdout(null), redirect_stderr(null):
                        snapshot=build_observation(client,now_utc=now,repo_sha=sha,
                              sequence=sequence,symbols=scan_symbols,
                              include_supplemental=True,allow_scan_symbols=True,
                              use_batch=True)
                if ws_observer is not None:
                    try:
                        snapshot["websocket_evidence"] = ws_observer.summary(observed_at_utc=now)
                    except Exception as exc:
                        exc._tickflow_stage="S4_WS_SUMMARY"
                        raise
                snapshot["postclose_evidence"] = _postclose_evidence(snapshot,datetime.now(timezone.utc))
                try:
                    atomic_publish(status_path,snapshot)
                except Exception as exc:
                    exc._tickflow_stage="S4_CACHE_PUBLISH"
                    raise
                print("TICKFLOW_RESEARCH_POLL=RESEARCH_ONLY_PASS",flush=True)
            except Exception as exc:
                failed=True
                failure=exc
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
                            "S4_WS_SUMMARY", "S4_CACHE_PUBLISH",
                            *[f"BATCH_{period}_FETCH"
                              for period in ("1M", "5M", "15M", "60M", "1D")],
                            *[f"S{i}_{period}_{action}"
                              for i in range(len(scan_symbols))
                              for period in ("1M","5M","15M","60M","1D")
                              for action in ("FETCH","NORMALIZE")],
                        } else "UNKNOWN"
                    ),
                    "symbols":{},"research_only":True,
                    "provider_first_target":True,
                    "source_arbiter_admission":"BLOCKED",
                    "radar_admission":"BLOCKED","live_trade":False,
                    "can_confirm_signal":False,"canonical_write_authorized":False,
                })
                print("TICKFLOW_RESEARCH_POLL=BLOCKED:"+type(exc).__name__,flush=True)
            network_failures = network_failures + 1 if failed else 0
            pause=(_network_retry_interval(datetime.now(timezone.utc), failure, network_failures)
                   if failed else _interval(datetime.now(timezone.utc)))
            # Interruptible shutdown, no runaway provider retry loop.
            for _ in range(pause):
                if not running: break
                time.sleep(1)
    finally:
        try:
            with open(os.devnull,"w",encoding="utf-8") as null:
                with redirect_stdout(null),redirect_stderr(null):
                    if ws_observer is not None:
                        client.stream.close()
                    client.close()
        except Exception:
            pass
    return 0

if __name__=="__main__":
    raise SystemExit(main())

