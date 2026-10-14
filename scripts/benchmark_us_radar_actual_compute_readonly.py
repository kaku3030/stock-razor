#!/usr/bin/env python3
"""Run the real US StockRadarTechnicalStateService CPU analysis on existing cached evidence.

Isolated in a one-shot separate process. No source provider queries, no writes,
no production worker mutation, no signal/trading admission. Synthetic market data
is not substituted for source; if cache invalid, report BLOCKED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
import json
import sys

RADAR_REPO = Path("/opt/stock-razor-us-radar/repo")
CANONICAL = Path("/run/stock-razor-us-livefeed/canonical-market-snapshot.json")
DAILY = Path("/run/stock-razor-us-livefeed/daily-history.json")
SYMBOLS = ("US.AMD", "US.NVDA", "US.TSLA", "US.QQQ")
ITERATIONS = 25

def percentile(vals, rank):
    if not vals:
        return None
    s = sorted(vals)
    pos = (len(s)-1)*rank/100
    i = int(pos)
    return round(s[i] + (s[min(i+1,len(s)-1)] - s[i])*(pos-i),3)

def main():
    result = {
        "schema": "stock_razor_us_radar_actual_compute_latency_v1",
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "study": "REAL_TECHNICAL_ENGINE_REPLAY_FROM_SAME_CANONICAL_CACHE",
        "iterations_requested": ITERATIONS,
        "provider_requests": 0,
        "production_writes": 0,
        "model_inference": False,
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "status": "BLOCKED",
    }
    if not RADAR_REPO.exists() or not CANONICAL.is_file():
        result["reason"] = "RUNTIME_CACHE_OR_REPO_UNAVAILABLE"
        return result
    sys.path.insert(0, str(RADAR_REPO))
    try:
        from src.services.stock_radar_v2.canonical_snapshot_worker import (
            load_canonical_snapshot_file
        )
        from src.services.stock_radar_v2.technical_state import (
            StockRadarTechnicalStateService
        )
        from src.services.stock_radar_v2.daily_history_reader import (
            load_futu_us_daily_history_frames
        )
        import pandas as pd
        start_load = perf_counter()
        source = load_canonical_snapshot_file(CANONICAL)
        cached_daily, daily_diagnostics = load_futu_us_daily_history_frames(
            DAILY, expected_repo_sha=source.repo_sha
        )
        load_ms = round((perf_counter()-start_load)*1000,3)
        selected = [s for s in source.snapshots if s.symbol in SYMBOLS]
        result["source_emitted_at_utc"] = source.emitted_at.isoformat()
        result["source_age_seconds"] = round(
            (datetime.now(timezone.utc)-source.emitted_at).total_seconds(),2)
        result["source_bar_closure"] = source.bar_closure
        result["source_delivery_mode"] = source.delivery_mode
        result["snapshot_load_and_parse_ms"] = load_ms
        result["canonical_symbols_present"] = len(selected)
        result["daily_history_validation"] = daily_diagnostics.get("status", "UNKNOWN")
        result["daily_symbols_present"] = sum(
            isinstance(cached_daily.get(s.symbol), pd.DataFrame)
            and not cached_daily[s.symbol].empty
            for s in selected
        )
        if len(selected) != len(SYMBOLS):
            result["reason"] = "CANONICAL_SYMBOLS_INCOMPLETE"
            return result
        if not all(s.minute_bars and s.bars_1h and s.bars_15m for s in selected):
            result["reason"] = "INCOMPLETE_INTRADAY_SNAPSHOTS"
            return result
        svc = StockRadarTechnicalStateService()
        # Warm analyzer imports/caches once; never writes back.
        for s in selected:
            state = svc.evaluate(s, daily=cached_daily.get(s.symbol))
            if state.research_only is not True or state.can_confirm_signal is not False:
                result["reason"] = "TECHNICAL_STATE_UNSAFE"
                return result
        batches=[]
        individual=[]
        for _ in range(ITERATIONS):
            start_batch=perf_counter()
            for s in selected:
                start_one=perf_counter()
                state=svc.evaluate(s,daily=cached_daily.get(s.symbol))
                ms=(perf_counter()-start_one)*1000
                individual.append(ms)
                if state.research_only is not True or state.can_confirm_signal is not False:
                    result["reason"]="TECHNICAL_STATE_UNSAFE"
                    return result
            batches.append((perf_counter()-start_batch)*1000)
        result.update({
            "status":"PASS_ISOLATED_REPLAY",
            "iterations_completed":len(batches),
            "symbol_evaluations":len(individual),
            "analysis_batch_p50_ms":percentile(batches,50),
            "analysis_batch_p95_ms":percentile(batches,95),
            "analysis_batch_max_ms":round(max(batches),3),
            "analysis_symbol_p50_ms":percentile(individual,50),
            "analysis_symbol_p95_ms":percentile(individual,95),
            "analysis_symbols":list(SYMBOLS),
            "live_data_freshness_qualified":False,
            "end_to_end_latency_qualified":False,
        })
    except Exception as exc:
        result["reason"] = "ANALYSIS_ERROR"
        result["failure_class"] = type(exc).__name__
    return result

if __name__=="__main__":
    print(json.dumps(main(),separators=(",",":"),sort_keys=True))
