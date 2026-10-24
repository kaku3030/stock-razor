#!/usr/bin/env python3
"""Fixed-rule annual replay, one-factor ablations and paired block statistics.

All historical windows remain REUSED_HISTORY, never untouched OOS. No provider,
parameter grid search, strategy admission or order routes are invoked.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.strategy_lab.s3_mtf import Rules, build_signals, metrics, prepare_replay, replay
from scripts.run_s3_mtf_research import load_bars, select_window


VARIANTS = {
    "BASE": {}, "D1_50_SLOPE": {"daily_filter": "50_slope"},
    "CONFIRM_2_HIGH": {"confirmation": "two_high"},
    "STRUCTURE_STOP": {"stop_mode": "structure"}, "ATR_STOP": {"stop_mode": "atr"},
    "STRUCTURE_EXIT": {"exit_mode": "structure_trail"},
    "SPLIT_50_50": {"first_risk_fraction": .5}, "NO_ADD": {"first_risk_fraction": 1.},
}


def daily_returns(curve, initial=100000.):
    x = curve.copy()
    x["end"] = pd.to_datetime(x.end, utc=True)
    eq = x.groupby(x.end.dt.tz_convert("America/New_York").dt.date).equity.last()
    ret = eq.pct_change()
    ret.iloc[0] = eq.iloc[0]/initial-1
    return pd.DataFrame({"equity": eq, "return": ret})


def block_test(delta, block, replicates=5000, seed=20261024):
    """Calendar-day paired moving blocks; portfolio symbols stay together."""
    x = np.asarray(delta, dtype=float)
    if not len(x) or not np.isfinite(x).all() or len(x) < 2*block:
        return {"status": "INSUFFICIENT_SAMPLE", "days": len(x), "block": block}
    rng = np.random.default_rng(seed)
    number = int(np.ceil(len(x)/block))
    samples = np.empty(replicates)
    for j in range(replicates):
        starts = rng.integers(0, len(x)-block+1, size=number)
        indices = (starts[:, None]+np.arange(block)).reshape(-1)[:len(x)]
        samples[j] = x[indices].mean()
    point = float(x.mean())
    # Bootstrap null is centered before its one-sided positive-edge test.
    centered = samples-point
    p = float((1+np.sum(centered >= point))/(replicates+1))
    return dict(status="EXPLORATORY_REUSED_HISTORY", days=len(x), block=block,
                replicates=replicates, seed=seed, mean_daily_difference=point,
                annualized_arithmetic_difference=point*252,
                ci95_annualized_arithmetic=(np.quantile(samples, [.025,.975])*252).tolist(),
                one_sided_null_bootstrap_p=p)


def holm(values):
    order = sorted(values, key=values.get)
    result, maximum = {}, 0.
    for rank, key in enumerate(order):
        maximum = max(maximum, (len(order)-rank)*values[key])
        result[key] = min(1., maximum)
    return result


def verify_primary(status, manifest_sha, module_sha, expected_rules):
    if (status["manifest_sha256"] != manifest_sha or status["source_sha256"] != module_sha
            or status["rules"] != expected_rules or status["TRADE_EXECUTION"] != "NO"
            or status["promotion"] != "NO"):
        raise ValueError("PRIMARY_PROVENANCE_OR_RULES_MISMATCH")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--primary", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    begun = time.perf_counter()
    m = json.loads(args.manifest.read_text())
    root = args.manifest.resolve().parent
    module_path = Path(__file__).resolve().parents[1]/"src/services/strategy_lab/s3_mtf.py"
    manifest_sha = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    primary_status = json.loads((args.primary/"status.json").read_text())
    expected_rules = asdict(Rules(**m.get("rules", {})))
    verify_primary(primary_status, manifest_sha, module_sha, expected_rules)
    schedule_path = root/m["schedule"]["path"]
    if hashlib.sha256(schedule_path.read_bytes()).hexdigest() != m["schedule"]["sha256"]:
        raise ValueError("SCHEDULE_HASH_MISMATCH")
    schedule = pd.read_csv(schedule_path)
    for k in ("open_at", "close_at"):
        if any(pd.Timestamp(x).tzinfo is None for x in schedule[k]):
            raise ValueError("SCHEDULE_EXPLICIT_OFFSETS_REQUIRED")
        schedule[k] = pd.to_datetime(schedule[k], utc=True)
    inputs = {x["symbol"]:load_bars(x, root) for x in m["symbols"]}
    sectors = {x["symbol"]:x["sector"] for x in m["symbols"]}
    qqq = load_bars(m["benchmark"], root)
    cache = prepare_replay(inputs, schedule)
    base = Rules(**m.get("rules", {}))
    memo, rows = {}, []

    def signals(arm, rules):
        key = (arm, json.dumps(asdict(rules), sort_keys=True))
        if key not in memo:
            memo[key] = {s:build_signals(x, schedule, arm, rules, prepared=cache, symbol=s)
                         for s,x in inputs.items()}
        return memo[key]

    def case(label, arm, rules, start, end, kind):
        ss = select_window(schedule, start, end)
        if int(schedule.close_at.searchsorted(ss.open_at.iloc[0])) < 200:
            raise ValueError("INSUFFICIENT_COMMON_WARMUP")
        sig = {s:x[(x.decision_at>=start)&(x.decision_at<=end)] if not x.empty else x
               for s,x in signals(arm, rules).items()}
        t,e,c = replay(inputs, schedule, sig, sectors, rules=rules, cost_bps=10.,
                       trade_start=ss.open_at.iloc[0], trade_end=ss.close_at.iloc[-1], prepared=cache)
        name = f"{kind}_{label}_{arm}"
        t.to_csv(args.output/f"{name}_trades.csv", index=False)
        e.to_csv(args.output/f"{name}_events.csv", index=False)
        daily_returns(c).to_csv(args.output/f"{name}_daily.csv")
        result = dict(kind=kind, label=label, arm=arm, cost_bps=10.,
                      actual_start=ss.open_at.iloc[0].isoformat(), actual_end=ss.close_at.iloc[-1].isoformat(),
                      **metrics(t,c))
        rows.append(result)
        pd.DataFrame(rows).to_csv(args.output/"validation_metrics.csv", index=False)
        print(json.dumps({"completed":name, "trades":len(t), "return":result["total_return"]}), flush=True)

    # Annual frozen-rule walk-forward: preceding history provides only causal
    # warmup; there is no parameter fitting on the following test year.
    for year in range(2022,2027):
        start = pd.Timestamp(f"{year}-01-01", tz="America/New_York")
        end = min(pd.Timestamp(f"{year+1}-01-01", tz="America/New_York"), schedule.close_at.iloc[-1])
        for arm in ("B","C","D","E"):
            case(str(year), arm, base, start, end, "FROZEN_WALK_FORWARD")
    for label, change in VARIANTS.items():
        for w in m["windows"]:
            if w["name"] == "full_2020_2026":
                continue
            case(label+"_"+w["name"], "B", replace(base, **change),
                 pd.Timestamp(w["start"]), pd.Timestamp(w["end"]), "ONE_FACTOR_ABLATION")
    primary = pd.read_csv(args.primary/"metrics.csv")
    statistics, p_values = {}, {}
    for window in ("full_2020_2026", "reused_holdout_2024_2026"):
        q = daily_returns(pd.read_csv(args.primary/f"{window}_QQQ_BH_10bps_equity.csv"))
        group = {}
        for arm in ("B","C","D","E"):
            s = daily_returns(pd.read_csv(args.primary/f"{window}_{arm}_10bps_equity.csv"))
            if not s.index.equals(q.index):
                raise ValueError("PAIRED_DAILY_GRID_MISMATCH")
            w = float(primary[(primary.window=="dev_2020_2021") & (primary.arm==arm)
                              & (primary.cost_bps==10)].mean_gross_exposure.iloc[0])
            # Fixed initial cash + QQQ units; weight learned only from the dev
            # window. Not an ex-post holdout exposure fit or daily rebalance.
            eq = (1-w)*100000+w*q.equity
            r = eq.pct_change()
            r.iloc[0] = eq.iloc[0]/100000-1
            tests = {}
            for name, baseline in (("QQQ_FULL",q["return"]),("QQQ_DEV_EXPOSURE_WEIGHT",r)):
                tests[name] = {str(block):block_test(s["return"]-baseline,block) for block in (20,60)}
                if name == "QQQ_DEV_EXPOSURE_WEIGHT" and window == "full_2020_2026":
                    for test in tests[name].values():
                        test["causality"] = "POST_HOC_DESCRIPTION_ONLY_DEV_OVERLAPS_EVALUATION"
                        test.pop("one_sided_null_bootstrap_p", None)
                if window == "reused_holdout_2024_2026":
                    p_values[arm+"_"+name] = max(t["one_sided_null_bootstrap_p"] for t in tests[name].values())
            group[arm] = dict(dev_fixed_initial_qqq_weight=w, tests=tests)
        statistics[window] = group
    status = dict(status="RETROSPECTIVE_RESEARCH_COMPLETED_WITH_A_BLOCKED", A="NO_FROZEN_D1_H1_M15_CONTRACT",
                  dataset_id=m["dataset_id"], history_reused=True, untouched_oos=False,
                  variants=VARIANTS, annual_validation="FROZEN_RULES_NO_REFITTING",
                  paired_block_tests=statistics, holm_adjusted_holdout_p=holm(p_values),
                  elapsed_seconds=time.perf_counter()-begun,
                  manifest_sha256=manifest_sha, strategy_source_sha256=module_sha,
                  primary_status_sha256=hashlib.sha256((args.primary/"status.json").read_bytes()).hexdigest(),
                  promotion="NO", TRADE_EXECUTION="NO")
    (args.output/"statistics.json").write_text(json.dumps(status, indent=2))
    print(json.dumps({"completed":True,"cases":len(rows),"elapsed_seconds":status["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
