#!/usr/bin/env python3
"""AWS EC2 read-only TickFlow continuity and MCP consumer acceptance evidence.

Only finite enums/ages/sequence/shas leave the AWS host. No market prices,
symbols payloads, provider secrets, orders, IAM or deployment mutations.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json, os
from pathlib import Path
import re, stat, subprocess, sys, time

WORKER_REPO=Path("/opt/stock-razor-cn-tickflow/repo")
WORKER_FILE=Path("/run/stock-razor-cn-tickflow/latest-research-observation.json")
MCP_REPO=Path("/opt/stock-razor-mcp/repo")
MCP_PY=Path("/opt/stock-razor-mcp/venv/bin/python")
WORKER_UNIT="stock-razor-cn-tickflow-research.service"
MCP_UNIT="stock-razor-mcp.service"
MAX_FILE_BYTES=150000
WHITELIST={"PASS_RESEARCH_ONLY","BAR_LABEL_BEHIND_SESSION","STALE","NO_DATA","INVALID_CACHE","INVALID_REQUEST"}
SHA=re.compile(r"^[0-9a-f]{40}$")
# Only these fixed exception classes can be projected from the private
# fail-closed cache. Never return provider message, stack trace or key.
_SAFE_FAILURE_CLASS={
    "ValueError":"VALUE_ERROR",
    "TypeError":"TYPE_ERROR",
    "KeyError":"KEY_ERROR",
    "RuntimeError":"RUNTIME_ERROR",
    "TimeoutError":"TIMEOUT_ERROR",
    "PermissionError":"PERMISSION_ERROR",
    "HTTPStatusError":"HTTP_STATUS_ERROR",
    "APIError":"API_ERROR",
    "TickFlowError":"TICKFLOW_ERROR",
    "AuthenticationError":"AUTH_ERROR",
    "RateLimitError":"RATE_LIMIT_ERROR",
    "ConnectionError":"CONNECTION_ERROR",
    "IndexError":"INDEX_ERROR",
    "AttributeError":"ATTRIBUTE_ERROR",
}

def blocked_status(failure_class: object) -> str:
    return "BLOCKED_"+_SAFE_FAILURE_CLASS.get(
        failure_class if isinstance(failure_class,str) else "", "OTHER"
    )


def active(service):
    try:
        p=subprocess.run(["systemctl","is-active",service],text=True,capture_output=True,timeout=5,check=False)
        return p.returncode==0 and p.stdout.strip()=="active"
    except (OSError, subprocess.TimeoutExpired):
        return False

def sample():
    result={
        "unit_active":active(WORKER_UNIT),
        "mcp_unit_active":active(MCP_UNIT),
        "status":"NOT_VERIFIED",
        "failure_stage":"UNKNOWN",
        "failure_reason":"UNKNOWN",
        "cache_private":False,
        "repo_sha_match":False,
        "cache_age_seconds":None,
        "sequence":None,
        "all_four_readonly_requests_ok":False,
        "per_period_observation":{},
        "mcp_cache_consumer":"NOT_VERIFIED",
    }
    try:
        meta=WORKER_FILE.stat()
        result["cache_private"]=stat.S_IMODE(meta.st_mode)==0o600
        if not 0<meta.st_size<=MAX_FILE_BYTES:
            raise ValueError("bounded cache bytes violated")
        data=json.loads(WORKER_FILE.read_text(encoding="utf-8"))
        if not isinstance(data,dict) or data.get("schema")!="stock_razor_cn_tickflow_research_observation_v0_1":
            raise ValueError("schema error")
        repo_sha=data.get("repo_sha")
        expect=(WORKER_REPO/".git").exists()
        actual=subprocess.run(["git","-C",str(WORKER_REPO),"rev-parse","HEAD"],
                              capture_output=True,text=True,timeout=5,check=False)
        result["repo_sha_match"]=bool(SHA.fullmatch(repo_sha or "")) and actual.returncode==0 and actual.stdout.strip()==repo_sha
        seq=data.get("sequence")
        result["sequence"]=seq if type(seq) is int and 0<seq<2**31 else None
        instant=datetime.fromisoformat(data["observed_at_utc"])
        age=(datetime.now(timezone.utc)-instant.astimezone(timezone.utc)).total_seconds()
        result["cache_age_seconds"]=round(age,2) if -5<=age<=100000 else None
        if data.get("status")=="BLOCKED":
            result["status"]=blocked_status(data.get("failure_class"))
            stage=data.get("failure_stage")
            allowed={f"S{i}_{period}_{action}"
                for i in range(2) for period in ("15M","60M")
                for action in ("FETCH","NORMALIZE")}
            result["failure_stage"]=stage if isinstance(stage,str) and stage in allowed else "UNKNOWN"
            reason=data.get("failure_reason")
            allowed_reasons={
                "UNSUPPORTED_PERIOD","CLOCK_MISSING_TZ",
                "COLUMN_MISSING_OR_NOT_LIST","COLUMN_LENGTH_MISMATCH",
                "ROW_COUNT_OUT_OF_BOUNDS","SDK_SHAPE_INVALID","ROW_TYPE_INVALID",
                "TIMESTAMP_TYPE_INVALID","TIMESTAMP_EPOCH_INVALID","TIMESTAMP_MISSING",
                "TIMESTAMP_ORDER_INVALID","HISTORICAL_SESSION_GRID_MISMATCH",
                "FUTURE_TRADING_DATE","OHLCVA_NUMBER_TYPE_INVALID",
                "OHLCVA_COLUMN_MISSING","OHLCVA_RELATION_INVALID",
                "VALID_BAR_COUNT_LOW","OTHER","NOT_APPLICABLE",
                "OHLCVA_NONPOSITIVE","OHLCVA_HIGH_LT_BODY","OHLCVA_LOW_GT_BODY",
                "OHLCVA_VOLUME_NEGATIVE","OHLCVA_AMOUNT_NEGATIVE",
            }
            result["failure_reason"]=reason if isinstance(reason,str) and reason in allowed_reasons else "UNKNOWN"
        elif data.get("status")=="PASS_RESEARCH_ONLY":
            result["status"]="CACHE_WRITTEN_RESEARCH"
        else:
            result["status"]="INVALID_CACHE"
    except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired):
        result["status"]="NO_VALID_CACHE"
        return result
    if not (result["unit_active"] and result["cache_private"] and result["repo_sha_match"]):
        result["status"]="INCOMPLETE"
    # Import exactly deployed original read-only research reader. Never
    # include the price-bearing rows or market data in public evidence.
    sys.path.insert(0,str(WORKER_REPO))
    try:
        from data_provider.cn_tickflow_research_cache import read_cn_tickflow_research_data
        for symbol in ("159611.SZ","518880.SH"):
            for period in ("15m","60m"):
                observation=read_cn_tickflow_research_data(symbol,period,limit=2)
                state=observation.get("status")
                if state not in WHITELIST: state="INVALID_CACHE"
                result["per_period_observation"][symbol.replace(".","_")+"_"+period]={
                    "state":state,
                    "rows":len(observation.get("rows",[])) if state=="PASS_RESEARCH_ONLY" else 0,
                    "source_age_seconds":observation.get("source_age_seconds") if state=="PASS_RESEARCH_ONLY" else None,
                    "has_session_progress":observation.get("expected_grid_progress")=="DUE_LABEL_PRESENT_NOT_FINALITY_PROOF",
                    "radar_blocked":observation.get("radar_admission")=="BLOCKED",
                    "finality_unproven":observation.get("bar_finality")=="NOT_VERIFIED",
                }
        result["all_four_readonly_requests_ok"]=all(
            x["state"]=="PASS_RESEARCH_ONLY" and x["rows"]>0
            and x["radar_blocked"] and x["finality_unproven"]
            for x in result["per_period_observation"].values()
        ) and len(result["per_period_observation"])==4
    except (ImportError,OSError,ValueError,TypeError):
        result["status"]="READER_EXCEPTION"
    # Import/call *deployed MCP app* isolated in its venv without prices.
    if MCP_PY.exists() and MCP_REPO.exists():
        code = """import sys;sys.path.insert(0,'/opt/stock-razor-mcp/repo')
from realtime_monitor.readonly_mcp_server import get_cn_tickflow_research_data
r=get_cn_tickflow_research_data('159611.SZ','15m',limit=2)
print('MCP_READ_OK' if r.get('ok') and r.get('radar_admission')=='BLOCKED' and
      r.get('research_only') is True and r.get('live_trade') is False else 'MCP_READ_BLOCKED')"""
        try:
            p=subprocess.run([str(MCP_PY),"-c",code],capture_output=True,text=True,timeout=12,check=False)
            result["mcp_cache_consumer"]="PASS" if p.returncode==0 and p.stdout.strip().endswith("MCP_READ_OK") else "BLOCKED"
        except (OSError,subprocess.TimeoutExpired):
            result["mcp_cache_consumer"]="BLOCKED"
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--interval",type=int,default=65)
    args=parser.parse_args()
    if not 0<=args.interval<=75:
        return 2
    before=sample()
    if args.interval: time.sleep(args.interval)
    after=sample()
    progressing=(type(before["sequence"]) is int and type(after["sequence"]) is int
                 and after["sequence"]>before["sequence"]
                 and before["unit_active"] and after["unit_active"])
    result={
        "schema":"stock_razor_tickflow_aws_research_acceptance_v0_1",
        "measurement":"EC2_SERVICE_CACHE_AND_MCP_READONLY_TWO_SAMPLES",
        "before":before,"after":after,
        "sequence_advanced":progressing,
        "limited_research_usable":bool(progressing and after["all_four_readonly_requests_ok"]
               and after["mcp_cache_consumer"]=="PASS" and after["cache_private"]
               and after["repo_sha_match"]),
        "exchange_finality":"NOT_VERIFIED",
        "cross_provider_parity":"NOT_VERIFIED",
        "source_arbiter_admission":"BLOCKED",
        "radar_admission":"BLOCKED","live_trade":"NO",
        "trade_execution":"NO","canonical_write":"NO",
    }
    print(json.dumps(result,separators=(",",":"),sort_keys=True))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
