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
    # Read-only REST, 4 batched-minute Kline requests per cadence, not ticks.
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
                              sequence=sequence,symbols=SYMBOLS)
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

