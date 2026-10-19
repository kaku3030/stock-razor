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
EASTMONEY_FILE=Path("/run/stock-razor-cn-eastmoney/latest-observation.json")
MCP_PY=Path("/opt/stock-razor-mcp/venv/bin/python")
WORKER_UNIT="stock-razor-cn-tickflow-research.service"
MCP_UNIT="stock-razor-mcp.service"
# Must match cn_tickflow_research_cache.MAX_BYTES (writer/read-cache 64 MB).
MAX_FILE_BYTES=64_000_000
WHITELIST={"PASS_RESEARCH_ONLY","BAR_LABEL_BEHIND_SESSION","STALE","NO_DATA","INVALID_CACHE","INVALID_REQUEST"}
SHA=re.compile(r"^[0-9a-f]{40}$")
CACHE_REJECTION_REASONS={
    "NONE","CACHE_SIZE_EXCEEDED","CACHE_UNREADABLE","CACHE_ENVELOPE_INVALID",
    "CACHE_SAFETY_FLAGS_INVALID","CACHE_REPO_SHA_INVALID","CACHE_OBSERVED_AT_INVALID",
    "CACHE_STALE","FRAME_OR_PERIOD_MISSING","BAR_COUNT_INVALID",
    "FRAME_METADATA_INVALID","BAR_RECORD_INVALID","BAR_LABEL_INVALID",
    "BAR_TIMESTAMP_INVALID","BAR_TIME_GRID_OR_FUTURE_INVALID","BAR_ORDER_INVALID",
    "BAR_NUMERIC_VALUE_INVALID","BAR_AMOUNT_INVALID","BAR_OHLC_INVALID",
    "CACHE_ROOT_INVALID","CACHE_SCHEMA_MISMATCH","CACHE_PROVIDER_MISMATCH","CACHE_STATUS_MISMATCH",
}
# Keep held ETFs first; 518880.SH is observation-only and is not a position.
HOLDINGS=("159611.SZ","159209.SZ","518880.SH","512730.SH","159363.SZ")
LIVE_PERIODS=("1m","5m","15m","60m")
RESEARCH_PERIODS=("1m","5m","15m","60m","1d")
FAILURE_REASON_CODES=frozenset((
    "UNSUPPORTED_PERIOD","CLOCK_MISSING_TZ",
    "COLUMN_MISSING_OR_NOT_LIST","COLUMN_LENGTH_MISMATCH",
    "ROW_COUNT_OUT_OF_BOUNDS","ROW_COUNT_BELOW_MIN","ROW_COUNT_ABOVE_MAX",
    "SDK_SHAPE_INVALID","ROW_TYPE_INVALID","TIMESTAMP_TYPE_INVALID",
    "TIMESTAMP_EPOCH_INVALID","TIMESTAMP_MISSING","TIMESTAMP_ORDER_INVALID",
    "HISTORICAL_SESSION_GRID_MISMATCH","FUTURE_TRADING_DATE",
    "OHLCVA_NUMBER_TYPE_INVALID","OHLCVA_COLUMN_MISSING",
    "OHLCVA_RELATION_INVALID","VALID_BAR_COUNT_LOW","OTHER","NOT_APPLICABLE",
    "OHLCVA_NONPOSITIVE","OHLCVA_HIGH_LT_BODY","OHLCVA_LOW_GT_BODY",
    "OHLCVA_VOLUME_NEGATIVE","OHLCVA_AMOUNT_NEGATIVE","CACHE_SIZE_EXCEEDED",
    "BATCH_SHAPE_INVALID","BATCH_SYMBOL_MISSING",
))

def safe_failure_reason(value: object) -> str:
    """Return only the finite worker failure vocabulary."""
    return value if isinstance(value,str) and value in FAILURE_REASON_CODES else "UNKNOWN"


def summarize_private_frame_progress(frame: object, *, timeframe: str, now_utc: datetime) -> dict:
    """Export no bars, prices, raw timestamps or provider credentials."""
    base={
        "last_due_grid":"UNKNOWN",
        "due_grid_continuity":"UNKNOWN",
        "dominant_quarantine_reason":"UNKNOWN",
        "quarantine_cause_buckets":{},
        "largest_ohlc_gap_bucket":"UNKNOWN",
        "gap_violation_rows_bucket":"UNKNOWN",
        "hilo_swap_candidate_bucket":"UNKNOWN",
        "etf_tick_grid_near_bucket":"UNKNOWN",
        "etf_tick_research_shadow_compatible_bucket":"UNKNOWN",
        "quarantined_rows_bucket":"UNKNOWN",
        "sdk_amount_omitted_bucket":"UNKNOWN",
        "vendor_float_rows_bucket":"UNKNOWN",
        "same_session_vendor_float_rows_bucket":"UNKNOWN",
        "retained_bar_count_bucket":"UNKNOWN",
    }
    if timeframe not in RESEARCH_PERIODS or not isinstance(frame,dict):
        return base
    rows=frame.get("rows")
    quarantined=frame.get("quarantined_unverified_rows_count")
    row_cap={"1m":240,"5m":144,"15m":96,"60m":24,"1d":40}[timeframe]
    minimum = 1 if timeframe == "60m" else 4
    if (not isinstance(rows,list) or not minimum<=len(rows)<=row_cap
            or type(quarantined) is not int or not 0<=quarantined<=row_cap):
        return base
    def bucket(n:int) -> str:
        return "ZERO" if n==0 else "ONE" if n==1 else "TWO_TO_FOUR" if n<=4 else "FIVE_PLUS"
    out={**base,"quarantined_rows_bucket":bucket(quarantined),
         "retained_bar_count_bucket":("ONE_TO_THREE" if len(rows)<4 else "FOUR_TO_24" if len(rows)<=24
                                      else "25_TO_96" if len(rows)<=96 else "97_TO_144")}
    reasons=frame.get("quarantine_reason_counts")
    allowed_reason=frozenset((
        "TODAY_LABEL_OFF_GRID","TODAY_FUTURE_LABEL",
        "TODAY_NONNUMERIC_OR_MISSING_VALUE","TODAY_NONPOSITIVE_OHLC",
        "TODAY_HIGH_BELOW_BODY","TODAY_LOW_ABOVE_BODY",
        "TODAY_NEGATIVE_VOLUME","TODAY_NEGATIVE_AMOUNT",
    ))
    if (isinstance(reasons,dict) and len(reasons)<=len(allowed_reason)
        and all(isinstance(k,str) and k in allowed_reason
                and type(v) is int and 0<v<=row_cap
                for k,v in reasons.items())
        and sum(reasons.values())==quarantined):
        out["dominant_quarantine_reason"]=(
            max(sorted(reasons),key=lambda k: reasons[k])
            if reasons else "NONE"
        )
        # Dominant cause alone hid a second, genuine malformed 15m row
        # under a newer future/forming label. Reveal only bounded fixed
        # enum names and count buckets; never provider values or timestamps.
        out["quarantine_cause_buckets"]={
            name:bucket(reasons[name]) for name in sorted(reasons)
        }
    gap_evidence=frame.get("quarantine_ohlc_gap_evidence")
    ordered=("GAP_LT_1BP","GAP_1_TO_10BP","GAP_10_TO_100BP","GAP_GE_100BP")
    swap_key="HILO_SWAP_WOULD_ENCLOSE_BODY"
    lattice_keys=("ETF_TICK_LATTICE_NEAR","ETF_TICK_LATTICE_FAR",
                  "ETF_LATTICE_QUANTIZE_WOULD_ENCLOSE_BODY")
    if (isinstance(gap_evidence,dict) and len(gap_evidence)<=8
            and all(k in (*ordered,swap_key,*lattice_keys)
                    and type(v) is int and 0<v<=row_cap
                    for k,v in gap_evidence.items())):
        gap_total=sum(gap_evidence.get(k,0) for k in ordered)
        swap=gap_evidence.get(swap_key,0)
        if gap_total<=quarantined and swap<=gap_total:
            out["gap_violation_rows_bucket"]=bucket(gap_total)
            out["hilo_swap_candidate_bucket"]=bucket(swap)
            out["largest_ohlc_gap_bucket"]=(
                next((key for key in reversed(ordered)
                      if gap_evidence.get(key,0)>0),"NONE")
            )
            near=gap_evidence.get(lattice_keys[0],0)
            far=gap_evidence.get(lattice_keys[1],0)
            repairable=gap_evidence.get(lattice_keys[2],0)
            if near+far==gap_total and repairable<=near:
                out["etf_tick_grid_near_bucket"]=bucket(near)
                out["etf_tick_research_shadow_compatible_bucket"]=bucket(repairable)
    try:
        omitted=sum(1 for row in rows if isinstance(row,dict)
                    and row.get("amount_availability")=="SDK_OMITTED")
        out["sdk_amount_omitted_bucket"]=bucket(omitted)
        import sys as _sys
        if str(WORKER_REPO) not in _sys.path:
            _sys.path.insert(0,str(WORKER_REPO))
        from data_provider.cn_tickflow_research_cache import (
            _expected_closed_grid_label, _LABEL_END, CN,
        )
        shnow=now_utc.astimezone(CN)
        if all(isinstance(row,dict)
               and row.get("ohlc_validation","STRICT") in (
                   "STRICT","VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY")
               for row in rows):
            tolerated=[
                row for row in rows
                if row.get("ohlc_validation")=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
            ]
            out["vendor_float_rows_bucket"]=bucket(len(tolerated))
            prefix=shnow.strftime("%Y-%m-%d")
            out["same_session_vendor_float_rows_bucket"]=bucket(
                sum(1 for row in tolerated if isinstance(row.get("label"),str)
                    and row["label"].startswith(prefix))
            )
        expected=_expected_closed_grid_label(now_utc,timeframe)
        if expected is None:
            out["last_due_grid"]="NO_SESSION_GRID_DUE"
            out["due_grid_continuity"]="NO_SESSION_GRID_DUE"
            return out
        rawlabel=rows[-1]["label"]
        last=datetime.strptime(rawlabel,"%Y-%m-%d %H:%M").replace(tzinfo=CN)
        if last.date()!=shnow.date():
            out["last_due_grid"]="NO_SAME_DAY_RETAINED_BAR"
            out["due_grid_continuity"]="NO_SAME_DAY_RETAINED_BAR"
            return out
        all_end=[]
        for clock in sorted(_LABEL_END[timeframe]):
            hh,mm=map(int,clock.split(":"))
            all_end.append(shnow.replace(hour=hh,minute=mm,
                                         second=0,microsecond=0))
        if last not in all_end:
            out["last_due_grid"]="LAST_LABEL_OFF_GRID"
            out["due_grid_continuity"]="INVALID_TODAY_LABEL_GRID"
            return out
        # Latest due label alone does not prove full intraday continuity.
        # Missing 09:45 followed by 10:00 used to appear caught-up.
        # Never export private labels or prices, only bounded fixed enums.
        # Matching schedule is NOT exchange finality or trade admission.
        due=frozenset(t for t in all_end if t<=expected)
        seen=set()
        invalid=False
        for item in rows:
            raw=item.get("label") if isinstance(item,dict) else None
            if not isinstance(raw,str):
                invalid=True
                break
            stamp=datetime.strptime(raw,"%Y-%m-%d %H:%M").replace(tzinfo=CN)
            if stamp.date()!=shnow.date():
                continue
            if stamp not in due or stamp in seen:
                invalid=True
                break
            seen.add(stamp)
        if invalid:
            out["due_grid_continuity"]="INVALID_TODAY_LABEL_GRID"
        else:
            missing=len(due-seen)
            out["due_grid_continuity"]=(
                "ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY" if missing==0 else
                "ONE_DUE_LABEL_MISSING" if missing==1 else
                "MULTIPLE_DUE_LABELS_MISSING"
            )
        missed=sum(last<x<=expected for x in all_end)
        out["last_due_grid"]=(
            "MATCHED_DUE_LABEL" if missed==0 else
            "ONE_DUE_BOUNDARY_MISSING" if missed==1 else
            "MULTIPLE_DUE_BOUNDARIES_MISSING"
        )
        return out
    except (ImportError,OSError,KeyError,ValueError,TypeError,IndexError,OverflowError):
        return out

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

def safe_cache_rejection_reason(value: object) -> str:
    return value if isinstance(value,str) and value in CACHE_REJECTION_REASONS else "UNKNOWN"


def blocked_status(failure_class: object) -> str:
    return "BLOCKED_"+_SAFE_FAILURE_CLASS.get(
        failure_class if isinstance(failure_class,str) else "", "OTHER"
    )



def safe_failure_stage(stage: object) -> str:
    """Mirror the worker's bounded batch and per-symbol research stage set.

    Supplemental 5m/1d are requested by the deployed worker even though the
    admission audit only qualifies 15m/60m. Do not silently erase their
    failed-stage evidence; never allow an arbitrary provider string through.
    """
    allowed={
        f"S{i}_{period}_{action}"
        for i in range(200)  # Same hard ceiling as the research collector.
        for period in ("1M", "15M", "60M", "5M", "1D")
        for action in ("FETCH", "NORMALIZE")
    }
    allowed.update({"S4_WS_SUMMARY", "S4_CACHE_PUBLISH"})
    allowed.update(f"BATCH_{period}_FETCH"
                   for period in ("1M", "5M", "15M", "60M", "1D"))
    return stage if isinstance(stage, str) and stage in allowed else "UNKNOWN"


def shadow_compare_eastmoney(tickflow: object, reference: object, *,
                             now_utc: datetime) -> dict:
    """Private cached-price parity: only categorical counts may leave EC2.

    No network, no provider subscription, no synthetic Klines, no source
    admission. Fail closed if reference time semantics are not qualified.
    """
    categories={}
    symbols=(("159611.SZ","159611"),("518880.SH","518880"))
    periods=("15m","60m")
    allowed_ohlc=("open","high","low","close")
    from math import isfinite
    from decimal import Decimal
    def bucket(n):
        return "ZERO" if n==0 else "ONE" if n==1 else (
            "TWO_TO_FOUR" if n<=4 else "FIVE_PLUS")
    for t_sym,e_sym in symbols:
        for period in periods:
            key=t_sym.replace(".","_")+"_"+period
            item={"status":"NOT_VERIFIED","overlap_bucket":"UNKNOWN",
                  "max_price_difference_ticks":"UNKNOWN","lineage":"UNKNOWN"}
            categories[key]=item
            try:
                if not isinstance(tickflow,dict) or not isinstance(reference,dict):
                    continue
                if (reference.get("schema")!="stock_razor_cn_eastmoney_observation_v1"
                    or reference.get("research_only") is not True
                    or reference.get("radar_admission")!="BLOCKED"
                    or reference.get("live_trade") is not False):
                    item["status"]="INVALID_REFERENCE"
                    continue
                timestamp=datetime.fromisoformat(reference["emitted_at_utc"])
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    item["status"]="INVALID_REFERENCE"
                    continue
                age=(now_utc-timestamp.astimezone(timezone.utc)).total_seconds()
                if not -5<=age<=240:
                    item["status"]="STALE_REFERENCE"
                    continue
                fr=reference["symbols"][e_sym]["timeframes"][period]
                tick_rows=tickflow["symbols"][t_sym][period]["rows"]
                if not isinstance(tick_rows,list) or not 4<=len(tick_rows)<=96:
                    item["status"]="INVALID_TICKFLOW_ROWS"
                    continue
                if (not isinstance(fr,dict) or fr.get("status")!="PASS"
                        or fr.get("adjustment")!="NONE"):
                    item["status"]="INVALID_REFERENCE"
                    continue
                lineage=fr.get("provider_used")
                if lineage not in ("eastmoney","tencent"):
                    item["status"]="INVALID_REFERENCE"
                    continue
                item["lineage"]=lineage.upper()
                qual=fr.get("timestamp_qualification")
                if (fr.get("timestamp_semantic")!="BAR_END"
                        or not isinstance(qual,dict)
                        or qual.get("status")!="PASS"
                        or qual.get("timestamp_semantic")!="BAR_END"):
                    item["status"]="UNQUALIFIED_REFERENCE_GRID"
                    continue
                erows=fr.get("rows")
                if not isinstance(erows,list) or not erows:
                    item["status"]="INVALID_REFERENCE"
                    continue
                mapped={}
                for bar in erows:
                    if not isinstance(bar,dict):
                        raise ValueError("reference row invalid")
                    label=bar.get("label")
                    if not isinstance(label,str) or len(label)!=16:
                        raise ValueError("reference label invalid")
                    if bar.get("quality_flags") not in ([],()):
                        continue
                    mapped[label]=bar
                diffs=[]
                for row in tick_rows:
                    if not isinstance(row,dict): raise ValueError("tickflow row invalid")
                    reference_row=mapped.get(row.get("label"))
                    if reference_row is None: continue
                    pairs=[]
                    for field in allowed_ohlc:
                        tv=row.get(field)
                        ev=reference_row.get(field)
                        if (type(tv) not in (float,int) or type(ev) not in (float,int)
                                or not isfinite(tv) or not isfinite(ev)
                                or tv<=0 or ev<=0):
                            raise ValueError("OHLC shadow number invalid")
                        pairs.append(abs(Decimal(str(tv))-Decimal(str(ev))))
                    diffs.append(max(pairs))
                item["overlap_bucket"]=bucket(len(diffs))
                if not diffs:
                    item["status"]="NO_OVERLAP"
                    continue
                maxdiff=max(diffs)
                tick=Decimal("0.001")
                item["max_price_difference_ticks"]=(
                    "EXACT" if maxdiff==0 else
                    "UNDER_HALF_TICK" if maxdiff<tick/2 else
                    "UP_TO_ONE_TICK" if maxdiff<=tick else
                    "UP_TO_TWO_TICKS" if maxdiff<=tick*2 else
                    "OVER_TWO_TICKS"
                )
                item["status"]=("OBSERVED_NOT_ADMITTED" if len(diffs)>=4
                                else "INSUFFICIENT_OVERLAP")
            except (OSError,ValueError,TypeError,KeyError,OverflowError,ArithmeticError):
                item["status"]="INVALID_SNAPSHOT"
                item["overlap_bucket"]="UNKNOWN"
                item["max_price_difference_ticks"]="UNKNOWN"
    return categories


def compare_tencent_qualified_price_rows(
    tickflow_rows: object, reference_rows: object, *,
    qualification_pass: bool, session_date: str|None=None,
) -> dict:
    """No raw price, timestamp or provider rows leave private AWS process."""
    result={"status":"UNQUALIFIED_GRID","overlap_bucket":"UNKNOWN",
            "max_ohlc_price_difference_ticks":"UNKNOWN",
            "earlier_session_agreement":"UNKNOWN",
            "same_session_agreement":"UNKNOWN",
            "earlier_session_overlap_bucket":"UNKNOWN",
            "same_session_overlap_bucket":"UNKNOWN",
            "same_session_disagreement_driver":"UNKNOWN",
            "same_session_disagreement_phase":"UNKNOWN",
            "same_session_disagreement_bucket":"UNKNOWN",
            "reference":"TENCENT_QUALIFIED_ONLY"}
    if qualification_pass is not True:
        return result
    result["status"]="INVALID_ROWS"
    if (not isinstance(tickflow_rows,list) or not 4<=len(tickflow_rows)<=96
            or not isinstance(reference_rows,(list,tuple))
            or not 48<=len(reference_rows)<=120):
        return result
    from decimal import Decimal
    from math import isfinite
    mapped={}
    for bar in reference_rows:
        if not isinstance(bar,dict):
            return result
        label=bar.get("label")
        if not isinstance(label,str) or len(label)!=16:
            return result
        if bar.get("quality_flags") not in ([],()):
            continue
        mapped[label]=bar
    diffs=[]
    dated_diffs=[]
    session_disagreements=[]
    for bar in tickflow_rows:
        if not isinstance(bar,dict):
            return result
        against=mapped.get(bar.get("label"))
        if against is None: continue
        try:
            values=[]
            for field in ("open","high","low","close"):
                x=bar[field]; y=against[field]
                if (type(x) not in (int,float) or type(y) not in (int,float)
                        or not isfinite(x) or not isfinite(y) or x<=0 or y<=0):
                    return result
                values.append(abs(Decimal(str(x))-Decimal(str(y))))
            diff=max(values)
            diffs.append(diff)
            label=bar.get("label")
            if not isinstance(label,str) or len(label)!=16:
                return result
            dated_diffs.append((label[:10],diff))
            if (isinstance(session_date,str) and len(session_date)==10
                    and label[:10]==session_date
                    and diff>Decimal("0.001")):
                drivers=[field for field,delta in
                         zip(("OPEN","HIGH","LOW","CLOSE"),values)
                         if delta==diff]
                driver=(drivers[0] if len(drivers)==1 else "MULTIPLE_FIELDS")
                clock=label[11:16]
                phase=(
                    "OPENING" if "09:30"<=clock<"10:30" else
                    "LATE_MORNING" if "10:30"<=clock<="11:30" else
                    "AFTERNOON" if "13:00"<=clock<"14:30" else
                    "CLOSING" if "14:30"<=clock<="15:00" else
                    "OTHER_SESSION_CLOCK"
                )
                session_disagreements.append((driver,phase))
        except (KeyError,ValueError,TypeError,ArithmeticError):
            return result
    count=len(diffs)
    result["overlap_bucket"]=(
        "ZERO" if count==0 else "ONE" if count==1 else
        "TWO_TO_FOUR" if count<=4 else "FIVE_PLUS"
    )
    if not count:
        result["status"]="NO_OVERLAP"
        return result
    mx=max(diffs)
    tick=Decimal("0.001")
    result["max_ohlc_price_difference_ticks"]=(
        "EXACT" if mx==0 else
        "UNDER_HALF_TICK" if mx<tick/2 else
        "UP_TO_ONE_TICK" if mx<=tick else
        "UP_TO_TWO_TICKS" if mx<=tick*2 else "OVER_TWO_TICKS"
    )
    def agree(deltas):
        count=len(deltas)
        overlap=("ZERO" if count==0 else "ONE" if count==1 else
                 "TWO_TO_FOUR" if count<=4 else "FIVE_PLUS")
        if count<4:
            return ("NO_OVERLAP" if count==0 else "INSUFFICIENT_PAIRS"),overlap
        within=sum(x<=tick for x in deltas)
        if within==count:
            return "ALL_WITHIN_ONE_TICK",overlap
        if within==0:
            return "NONE_WITHIN_ONE_TICK",overlap
        ratio=within*100//count
        return ("GE90_PCT" if ratio>=90 else
                "GE50_PCT" if ratio>=50 else
                "GE25_PCT" if ratio>=25 else "LT25_PCT"),overlap
    if (session_date is not None and isinstance(session_date,str)
            and len(session_date)==10):
        past=[delta for date,delta in dated_diffs if date<session_date]
        today=[delta for date,delta in dated_diffs if date==session_date]
        result["earlier_session_agreement"],result["earlier_session_overlap_bucket"]=agree(past)
        result["same_session_agreement"],result["same_session_overlap_bucket"]=agree(today)
        if len(today)>=4:
            n=len(session_disagreements)
            result["same_session_disagreement_bucket"]=(
                "ZERO" if n==0 else "ONE" if n==1 else
                "TWO_TO_FOUR" if n<=4 else "FIVE_PLUS"
            )
            drivers={v[0] for v in session_disagreements}
            phases={v[1] for v in session_disagreements}
            result["same_session_disagreement_driver"]=(
                "NONE" if not drivers else
                next(iter(drivers)) if len(drivers)==1 else "MULTIPLE_DRIVERS"
            )
            result["same_session_disagreement_phase"]=(
                "NONE" if not phases else
                next(iter(phases)) if len(phases)==1 else "MULTIPLE_PHASES"
            )
    result["status"]=(
        "OBSERVED_NOT_ADMITTED" if count>=4 else "INSUFFICIENT_OVERLAP"
    )
    return result



def eastmoney_tencent_historical_grid_shadow(
    cached: object, tencent_rows: object, *, symbol: str, timeframe: str,
    qualified: bool, now_utc: datetime,
) -> str:
    """Three-session, independent, historical-only label AND OHLC witness.

    NOT proof of currentness or source admission; production Eastmoney
    observer retains UNKNOWN semantics and no price values are exported.
    """
    if not qualified:
        return "TENCENT_UNQUALIFIED"
    if symbol not in ("159611","518880") or timeframe not in ("15m","60m"):
        return "UNKNOWN"
    try:
        from decimal import Decimal
        from math import isfinite
        from zoneinfo import ZoneInfo
        from src.services.a_share_intraday_grid_qualification import _EXPECTED_END_LABELS
        if not isinstance(cached,dict):
            return "NO_FRESH_REFERENCE"
        if (cached.get("schema")!="stock_razor_cn_eastmoney_observation_v1"
                or cached.get("research_only") is not True
                or cached.get("radar_admission")!="BLOCKED"
                or cached.get("live_trade") is not False):
            return "INVALID_REFERENCE"
        stamp=datetime.fromisoformat(cached["emitted_at_utc"])
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return "INVALID_REFERENCE"
        if not -5 <= (now_utc-stamp.astimezone(timezone.utc)).total_seconds() <= 240:
            return "NO_FRESH_REFERENCE"
        frame=cached["symbols"][symbol]["timeframes"][timeframe]
        if (frame.get("status")!="PASS" or frame.get("adjustment")!="NONE"
                or frame.get("provider_used")!="eastmoney"
                or frame.get("timestamp_semantic")!="UNKNOWN"
                or frame.get("timestamp_qualification") is not None):
            return "UNQUALIFIED_REFERENCE_LINEAGE"
        cutoff=now_utc.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        grid=tuple(_EXPECTED_END_LABELS[int(timeframe[:-1])])
        def group(rows,source):
            if not isinstance(rows,(list,tuple)):
                raise ValueError("invalid input")
            previous=""
            result={}
            for bar in rows:
                if (not isinstance(bar,dict) or bar.get("provider")!=source
                        or bar.get("quality_flags") not in ([],())):
                    raise ValueError("invalid source provenance")
                label=bar.get("label")
                if (not isinstance(label,str) or len(label)!=16
                        or label<=previous or
                        datetime.strptime(label,"%Y-%m-%d %H:%M").strftime("%Y-%m-%d %H:%M")!=label):
                    raise ValueError("invalid label")
                previous=label
                if source=="eastmoney" and bar.get("provider_label_raw")!=label:
                    raise ValueError("not original label")
                if label[:10]>=cutoff:
                    continue
                clock=label[11:]
                if clock not in grid:
                    raise ValueError("off-grid history")
                numbers=[]
                for field in ("open","high","low","close"):
                    value=bar.get(field)
                    if type(value) not in (int,float) or not isfinite(value) or value<=0:
                        raise ValueError("invalid OHLC")
                    numbers.append(Decimal(str(value)))
                result.setdefault(label[:10],[]).append((clock,numbers))
            return result
        east=group(frame["rows"],"eastmoney")
        teng=group(tencent_rows,"tencent")
        sessions=[]
        for date in sorted(set(east)&set(teng)):
            a,b=east[date],teng[date]
            if tuple(v[0] for v in a)==grid and tuple(v[0] for v in b)==grid:
                sessions.append((a,b))
        if len(sessions)<3:
            return "INSUFFICIENT_SHARED_COMPLETE_SESSIONS"
        n=0
        within=0
        for a,b in sessions[-3:]:
            for (_,left),(_,right) in zip(a,b):
                n+=1
                if max(abs(x-y) for x,y in zip(left,right))<=Decimal("0.001"):
                    within+=1
        if within*100>=90*n:
            return "HISTORICAL_GRID_PRICE_ALIGNED_RESEARCH_ONLY"
        return "HISTORICAL_GRID_ALIGNED_PRICE_DIVERGENCE"
    except (KeyError,ValueError,TypeError,IndexError,OverflowError,ArithmeticError):
        return "INVALID_REFERENCE"

def sample_tencent_qualified_parity() -> dict:
    """At most FOUR public Tencent REST GETs, exactly 2 ETF × 15m/60m.

    Research shadow only. Grid qualification + price rows remain private.
    """
    base={
        key.replace(".","_")+"_"+period: {
            "status":"NO_PRIVATE_TICKFLOW_SNAPSHOT",
            "overlap_bucket":"UNKNOWN",
            "max_ohlc_price_difference_ticks":"UNKNOWN",
            "reference":"TENCENT_QUALIFIED_ONLY",
            "earlier_session_agreement":"UNKNOWN",
            "same_session_agreement":"UNKNOWN",
            "earlier_session_overlap_bucket":"UNKNOWN",
            "same_session_overlap_bucket":"UNKNOWN",
            "same_session_disagreement_driver":"UNKNOWN",
            "same_session_disagreement_phase":"UNKNOWN",
            "same_session_disagreement_bucket":"UNKNOWN",
            "eastmoney_historical_grid_shadow":"UNKNOWN",
        }
        for key in ("159611.SZ","518880.SH")
        for period in ("15m","60m")
    }
    try:
        meta=WORKER_FILE.stat()
        if not 0<meta.st_size<=MAX_FILE_BYTES or stat.S_IMODE(meta.st_mode)!=0o600:
            return base
        payload=json.loads(WORKER_FILE.read_text(encoding="utf-8"))
        if (not isinstance(payload,dict)
            or payload.get("schema")!="stock_razor_cn_tickflow_research_observation_v0_1"
            or payload.get("status")!="PASS_RESEARCH_ONLY"
            or payload.get("source_arbiter_admission")!="BLOCKED"
            or payload.get("radar_admission")!="BLOCKED"
            or payload.get("live_trade") is not False):
            return base
    except (OSError,ValueError,TypeError):
        return base
    # Existing provider parser + repeated historical grid qualification.
    # Neither the Binance SDK nor TickFlow paid HTTP are called.
    if str(WORKER_REPO) not in sys.path:
        sys.path.insert(0,str(WORKER_REPO))
    try:
        from data_provider.cn_eastmoney_cloud_observer import (
            _http_json,build_tencent_kline_url,parse_tencent_kline_rows)
        from src.services.a_share_intraday_grid_qualification import (
            qualify_intraday_end_label_grid)
    except ImportError:
        for item in base.values():
            item["status"]="IMPORT_BLOCKED"
        return base
    try:
        m=EASTMONEY_FILE.stat()
        ecache=json.loads(EASTMONEY_FILE.read_text(encoding="utf-8")) if 0<m.st_size<=4000000 else None
    except (OSError,ValueError,TypeError):
        ecache=None
    for key,code in (("159611.SZ","159611"),("518880.SH","518880")):
        for period in ("15m","60m"):
            out=base[key.replace(".","_")+"_"+period]
            try:
                frame=payload["symbols"][key][period]
                tickrows=frame["rows"]
                url=build_tencent_kline_url(code,period,limit=120)
                if not url.startswith("https://ifzq.gtimg.cn/appstock/app/kline/mkline?"):
                    out["status"]="URL_NOT_ALLOWLISTED"
                    continue
                # Hard budget: one request per fixed pair, timeout 4sec,
                # max_attempts 1 (no implicit retries).
                raw=_http_json(url,timeout_seconds=4.0,max_attempts=1)
                reference=list(parse_tencent_kline_rows(
                    raw,symbol=code,timeframe=period))
                qualification=qualify_intraday_end_label_grid(
                    [row["label"] for row in reference],
                    source_token="tencent",
                    endpoint_id="tencent.kline_intraday",
                    interval_minutes=int(period[:-1]),
                )
                from zoneinfo import ZoneInfo
                cn_day=datetime.now(timezone.utc).astimezone(
                    ZoneInfo("Asia/Shanghai")
                ).date().isoformat()
                out.update(compare_tencent_qualified_price_rows(
                    tickrows,reference,
                    qualification_pass=qualification.status=="PASS",
                    session_date=cn_day,
                ))
                out["eastmoney_historical_grid_shadow"]=(
                    eastmoney_tencent_historical_grid_shadow(
                        ecache,reference,symbol=code,timeframe=period,
                        qualified=qualification.status=="PASS",
                        now_utc=datetime.now(timezone.utc),
                    )
                )
            except Exception:
                # Keep errors and HTTP payloads private; classify only.
                out["status"]="PROVIDER_OR_PARSER_BLOCKED"
    return base


def active(service):
    try:
        p=subprocess.run(["systemctl","is-active",service],text=True,capture_output=True,timeout=5,check=False)
        return p.returncode==0 and p.stdout.strip()=="active"
    except (OSError, subprocess.TimeoutExpired):
        return False


def safe_worker_journal_observation() -> str:
    """Read only this fixed worker's last 10m sanitized lifecycle markers.

    Raw journal bytes, messages, provider errors and credentials MUST NOT
    leave the host or enter the sanitized GitHub Actions output.
    """
    try:
        result=subprocess.run([
            "journalctl", "--unit", WORKER_UNIT, "--since=-10minutes",
            "--lines=64", "--output=cat", "--no-pager", "--quiet",
        ], text=True, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "JOURNAL_UNAVAILABLE"
    if result.returncode != 0:
        return "JOURNAL_UNAVAILABLE"
    for line in reversed(result.stdout.splitlines()):
        value=line.strip()
        if value=="TICKFLOW_RESEARCH_POLL=RESEARCH_ONLY_PASS":
            return "POLL_RESEARCH_ONLY_PASS"
        if value.startswith("TICKFLOW_RESEARCH_POLL=BLOCKED:"):
            # The worker emits only its exception class but the journal
            # might contain malformed/attacker text: reveal only our enum.
            return "POLL_BLOCKED"
        if value.startswith("TICKFLOW_RESEARCH_BOOT=BLOCKED:"):
            return "BOOT_BLOCKED"
    return "NO_RECENT_LIFECYCLE_MARKER"


def sample():
    result={
        "unit_active":active(WORKER_UNIT),
        "mcp_unit_active":active(MCP_UNIT),
        "worker_journal_observation":safe_worker_journal_observation(),
        "status":"NOT_VERIFIED",
        "failure_class":"UNKNOWN",
        "cache_unavailable_reason":"NOT_APPLICABLE",
        "failure_stage":"UNKNOWN",
        "failure_reason":"UNKNOWN",
        "failure_ohlc_float_gap_bucket":"UNKNOWN",
        "cache_private":False,
        "repo_sha_match":False,
        "worker_source_matches_main":False,
        "mcp_source_matches_main":False,
        "cache_age_seconds":None,
        "source_frame_progress":{},
        "supplemental_5m_reader":{},
        "independent_price_shadow":{},
        "sequence":None,
        "all_four_readonly_requests_ok":False,
        "per_period_observation":{},
        "all_four_historical_requests_ok":False,
        "historical_period_observation":{},
        "mcp_historical_consumer":"NOT_VERIFIED",
        "mcp_cache_consumer":"NOT_VERIFIED",
        "mcp_read_failure_reason":"NOT_VERIFIED",
    }
    try:
        try:
            meta=WORKER_FILE.stat()
        except FileNotFoundError:
            result["cache_unavailable_reason"]="FILE_MISSING"
            raise
        except PermissionError:
            result["cache_unavailable_reason"]="FILE_PERMISSION_BLOCKED"
            raise
        result["cache_private"]=stat.S_IMODE(meta.st_mode)==0o600
        if not 0<meta.st_size<=MAX_FILE_BYTES:
            result["cache_unavailable_reason"]="FILE_SIZE_INVALID"
            raise ValueError("bounded cache bytes violated")
        try:
            data=json.loads(WORKER_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result["cache_unavailable_reason"]="JSON_INVALID"
            raise
        except UnicodeError:
            result["cache_unavailable_reason"]="DECODE_INVALID"
            raise
        if not isinstance(data,dict) or data.get("schema")!="stock_razor_cn_tickflow_research_observation_v0_1":
            result["cache_unavailable_reason"]="SCHEMA_INVALID"
            raise ValueError("schema error")
        repo_sha=data.get("repo_sha")
        expect=(WORKER_REPO/".git").exists()
        actual=subprocess.run(["git","-C",str(WORKER_REPO),"rev-parse","HEAD"],
                              capture_output=True,text=True,timeout=5,check=False)
        result["repo_sha_match"]=bool(SHA.fullmatch(repo_sha or "")) and actual.returncode==0 and actual.stdout.strip()==repo_sha
        expected_main_sha=os.environ.get("STOCK_RAZOR_EXPECTED_MAIN_SHA","")
        result["worker_source_matches_main"]=(
            bool(SHA.fullmatch(expected_main_sha)) and actual.returncode==0
            and actual.stdout.strip()==expected_main_sha
        )
        seq=data.get("sequence")
        result["sequence"]=seq if type(seq) is int and 0<seq<2**31 else None
        instant=datetime.fromisoformat(data["observed_at_utc"])
        age=(datetime.now(timezone.utc)-instant.astimezone(timezone.utc)).total_seconds()
        result["cache_age_seconds"]=round(age,2) if -5<=age<=100000 else None
        if data.get("status")=="PASS_RESEARCH_ONLY":
            # No provider I/O: read already cached independent-lineage
            # Eastmoney/Tencent observer, NEVER export the price-bearing rows.
            try:
                emeta=EASTMONEY_FILE.stat()
                if not 0<emeta.st_size<=4000000:
                    raise ValueError("reference cache length")
                reference=json.loads(EASTMONEY_FILE.read_text(encoding="utf-8"))
            except (OSError,ValueError,TypeError):
                reference=None
            result["independent_price_shadow"]=shadow_compare_eastmoney(
                data,reference,now_utc=datetime.now(timezone.utc)
            )
            # Sanitize private, price-bearing cache *before* result leaves EC2.
            for symbol in HOLDINGS:
                for period in RESEARCH_PERIODS:
                    try:
                        frame=data["symbols"][symbol][period]
                    except (KeyError,TypeError):
                        frame=None
                    result["source_frame_progress"][
                        symbol.replace(".","_")+"_"+period
                    ]=summarize_private_frame_progress(
                        frame,timeframe=period,now_utc=datetime.now(timezone.utc),
                    )
        if data.get("status")=="BLOCKED":
            result["status"]=blocked_status(data.get("failure_class"))
            failure_class=data.get("failure_class")
            allowed_failure_classes={
                "ValueError","TypeError","KeyError","ImportError","OSError",
                "TimeoutError","ConnectionError","ConnectTimeout","ReadTimeout",
                "WriteTimeout","PoolTimeout","ConnectError","ReadError",
                "RemoteProtocolError","JSONDecodeError","InvalidOperation",
            }
            result["failure_class"]=(
                failure_class if isinstance(failure_class,str)
                and failure_class in allowed_failure_classes else "UNKNOWN"
            )
            result["failure_stage"]=safe_failure_stage(data.get("failure_stage"))
            result["failure_reason"]=safe_failure_reason(data.get("failure_reason"))
            precision=data.get("failure_ohlc_float_gap_bucket")
            result["failure_ohlc_float_gap_bucket"]=(
                precision if isinstance(precision,str)
                and precision in ("WITHIN_1E_MINUS_5","OVER_1E_MINUS_5")
                else "UNKNOWN"
            )
        elif data.get("status")=="PASS_RESEARCH_ONLY":
            result["status"]="CACHE_WRITTEN_RESEARCH"
        else:
            result["status"]="INVALID_CACHE"
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,subprocess.TimeoutExpired):
        result["status"]="NO_VALID_CACHE"
        if result["cache_unavailable_reason"]=="NOT_APPLICABLE":
            result["cache_unavailable_reason"]="UNCLASSIFIED"
        return result
    if not (result["unit_active"] and result["cache_private"] and result["repo_sha_match"]):
        result["status"]="INCOMPLETE"
    # Import exactly deployed original read-only research reader. Never
    # include the price-bearing rows or market data in public evidence.
    sys.path.insert(0,str(WORKER_REPO))
    try:
        from data_provider.cn_tickflow_research_cache import read_cn_tickflow_research_data
        for symbol in HOLDINGS:
            for period in LIVE_PERIODS:
                observation=read_cn_tickflow_research_data(symbol,period,limit=2)
                state=observation.get("status")
                if state not in WHITELIST: state="INVALID_CACHE"
                result["per_period_observation"][symbol.replace(".","_")+"_"+period]={
                    "state":state,
                    "cache_rejection_reason":safe_cache_rejection_reason(
                        observation.get("cache_rejection_reason","NONE")
                    ),
                    "rows":len(observation.get("rows",[])) if state=="PASS_RESEARCH_ONLY" else 0,
                    "source_age_seconds":observation.get("source_age_seconds") if state=="PASS_RESEARCH_ONLY" else None,
                    "has_session_progress":observation.get("expected_grid_progress")=="DUE_LABEL_PRESENT_NOT_FINALITY_PROOF",
                    "radar_blocked":observation.get("radar_admission")=="BLOCKED",
                    "finality_unproven":observation.get("bar_finality")=="NOT_VERIFIED",
                    "ohlc_precision_scope":(
                        observation.get("ohlc_precision_scope")
                        if state=="PASS_RESEARCH_ONLY"
                        and observation.get("ohlc_precision_scope") in (
                            "STRICT","VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY")
                        else "UNKNOWN"
                    ),
                }
        # The complete matrix is read from the already-written private cache.
        # It never grants currentness, closure or Radar admission.
        for symbol in HOLDINGS:
            for period in LIVE_PERIODS:
                obs=read_cn_tickflow_research_data(
                    symbol,period,limit=2,research_mode="session_progress")
                state=obs.get("status")
                if state not in WHITELIST:
                    state="INVALID_CACHE"
                result["supplemental_5m_reader"][symbol.replace(".","_")+"_"+period]={
                    "state":state,
                    "finality_unproven":obs.get("bar_finality")=="NOT_VERIFIED",
                    "cache_rejection_reason":safe_cache_rejection_reason(
                        obs.get("cache_rejection_reason","NONE")
                    ),
                    "radar_blocked":obs.get("radar_admission")=="BLOCKED",
                    "rows":len(obs.get("rows",[]))
                        if state=="PASS_RESEARCH_ONLY" else 0,
                }
        result["all_four_readonly_requests_ok"]=all(
            x["state"]=="PASS_RESEARCH_ONLY" and x["rows"]>0
            and x["radar_blocked"] and x["finality_unproven"]
            for x in result["per_period_observation"].values()
        ) and len(result["per_period_observation"])==len(HOLDINGS)*len(LIVE_PERIODS)
        for symbol in HOLDINGS:
            for period in RESEARCH_PERIODS:
                hist=read_cn_tickflow_research_data(
                    symbol,period,limit=2,research_mode="historical_only",
                )
                hstatus=hist.get("status")
                if hstatus not in {"PASS_HISTORICAL_ONLY","STALE",
                        "NO_DATA","INVALID_CACHE","INVALID_REQUEST"}:
                    hstatus="INVALID_CACHE"
                result["historical_period_observation"][
                    symbol.replace(".","_")+"_"+period
                ]={
                    "state":hstatus,
                    "cache_rejection_reason":safe_cache_rejection_reason(
                        hist.get("cache_rejection_reason","NONE")
                    ),
                    "research_only":hist.get("research_only") is True,
                    "currentness_unproven":hist.get("currentness")=="UNPROVEN",
                    "radar_blocked":hist.get("radar_admission")=="BLOCKED",
                    "finality_unproven":hist.get("bar_finality")=="NOT_VERIFIED",
                    "rows":len(hist.get("rows",[])) if hstatus=="PASS_HISTORICAL_ONLY" else 0,
                }
        result["all_four_historical_requests_ok"]=(
            len(result["historical_period_observation"])==len(HOLDINGS)*len(RESEARCH_PERIODS)
            and all(
                h["state"]=="PASS_HISTORICAL_ONLY"
                and h["rows"]>0
                and h["research_only"] and h["currentness_unproven"]
                and h["radar_blocked"] and h["finality_unproven"]
                for h in result["historical_period_observation"].values()
            )
        )
    except (ImportError,OSError,ValueError,TypeError):
        result["status"]="READER_EXCEPTION"
    # Import/call *deployed MCP app* isolated in its venv without prices.
    if MCP_PY.exists() and MCP_REPO.exists():
        mcp_head=subprocess.run(["git","-C",str(MCP_REPO),"rev-parse","HEAD"],
                                capture_output=True,text=True,timeout=5,check=False)
        expected_main_sha=os.environ.get("STOCK_RAZOR_EXPECTED_MAIN_SHA","")
        result["mcp_source_matches_main"]=(
            bool(SHA.fullmatch(expected_main_sha)) and mcp_head.returncode==0
            and mcp_head.stdout.strip()==expected_main_sha
        )
        code = """import sys;sys.path.insert(0,'/opt/stock-razor-mcp/repo')
from realtime_monitor.readonly_mcp_server import get_cn_tickflow_research_data
r=get_cn_tickflow_research_data('159611.SZ','15m',limit=2)
print('MCP_READ_OK' if r.get('ok') and r.get('radar_admission')=='BLOCKED' and
      r.get('research_only') is True and r.get('live_trade') is False else 'MCP_READ_BLOCKED')"""
        try:
            p=subprocess.run([str(MCP_PY),"-c",code],capture_output=True,text=True,timeout=12,check=False)
            if p.returncode==0 and p.stdout.strip().endswith("MCP_READ_OK"):
                result["mcp_cache_consumer"]="PASS"
                result["mcp_read_failure_reason"]="NOT_APPLICABLE"
            else:
                result["mcp_cache_consumer"]="BLOCKED"
                result["mcp_read_failure_reason"]=(
                    "METHOD_RETURN_BLOCKED"
                    if p.returncode==0 and p.stdout.strip().endswith("MCP_READ_BLOCKED")
                    else "IMPORT_OR_RUNTIME_FAILURE"
                )
        except (OSError,subprocess.TimeoutExpired):
            result["mcp_cache_consumer"]="BLOCKED"
            result["mcp_read_failure_reason"]="IMPORT_OR_RUNTIME_FAILURE"
        # Historical mode is a distinct explicit research route; its success
        # cannot be counted toward session-current Radar/source admission.
        historical_code = """import sys;sys.path.insert(0,'/opt/stock-razor-mcp/repo')
from realtime_monitor.readonly_mcp_server import get_cn_tickflow_research_data
r=get_cn_tickflow_research_data('159611.SZ','15m',limit=2,
                               research_mode='historical_only')
print('MCP_HISTORY_OK' if r.get('ok') and
      r.get('status')=='PASS_HISTORICAL_ONLY' and
      r.get('research_only') is True and
      r.get('radar_admission')=='BLOCKED' and
      r.get('currentness')=='UNPROVEN' and
      r.get('bar_finality')=='NOT_VERIFIED' and
      r.get('live_trade') is False else 'MCP_HISTORY_BLOCKED')"""
        try:
            hist_proc=subprocess.run([str(MCP_PY),"-c",historical_code],
                capture_output=True,text=True,timeout=12,check=False)
            result["mcp_historical_consumer"]=(
                "PASS" if hist_proc.returncode==0
                and hist_proc.stdout.strip().endswith("MCP_HISTORY_OK")
                else "BLOCKED"
            )
        except (OSError,subprocess.TimeoutExpired):
            result["mcp_historical_consumer"]="BLOCKED"
    else:
        result["mcp_read_failure_reason"]="SERVICE_PATH_MISSING"
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
        "tencent_independent_shadow":sample_tencent_qualified_parity(),
        "sequence_advanced":progressing,
        "limited_research_usable":bool(progressing and after["all_four_readonly_requests_ok"]
               and after["mcp_cache_consumer"]=="PASS" and after["cache_private"]
               and after["repo_sha_match"]),
        "historical_research_usable":bool(
               after["all_four_historical_requests_ok"]
               and after["mcp_historical_consumer"]=="PASS"
               and after["cache_private"] and after["repo_sha_match"]
               and after["unit_active"] and after["mcp_unit_active"]
        ),
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
