#!/usr/bin/env python3
"""Owner-confirmed original S3 identity, with causal shared execution repairs.

Original D1/H1/SRVP signal, full 0.25% campaign risk, no new D1 exit or add.
The original 3840 observed-five-minute holding cap is retained. Decisions and
time exits execute strictly after availability, not at an already-past open.
"""
import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.run_s3_mtf_research import load_bars, select_window
from scripts.run_s3_mtf_validation import block_test, daily_returns, holm
from src.services.strategy_lab.s3_legacy_baseline import build_legacy_signals


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ["module","manifest","primary","output"]:
        ap.add_argument("--"+name,type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location("s3_legacy_execution",args.module)
    eng=importlib.util.module_from_spec(spec);sys.modules[spec.name]=eng;spec.loader.exec_module(eng)
    m=json.loads(args.manifest.read_text());root=args.manifest.resolve().parent
    ps=json.loads((args.primary/"status.json").read_text())
    if ps["manifest_sha256"]!=hashlib.sha256(args.manifest.read_bytes()).hexdigest():
        raise ValueError("PRIMARY_MANIFEST_MISMATCH")
    sp=root/m["schedule"]["path"]
    if hashlib.sha256(sp.read_bytes()).hexdigest()!=m["schedule"]["sha256"]:
        raise ValueError("SCHEDULE_HASH_MISMATCH")
    schedule=pd.read_csv(sp)
    for k in ["open_at","close_at"]:
        if any(pd.Timestamp(x).tzinfo is None for x in schedule[k]):raise ValueError("NAIVE_SCHEDULE")
        schedule[k]=pd.to_datetime(schedule[k],utc=True)
    inputs={x["symbol"]:load_bars(x,root) for x in m["symbols"]}
    sectors={x["symbol"]:x["sector"] for x in m["symbols"]}
    cache=eng.prepare_replay(inputs,schedule)
    rules=eng.Rules(first_risk_fraction=1.,max_sessions=1000000)
    generated={sym:build_legacy_signals(x,schedule,prepared=cache,symbol=sym) for sym,x in inputs.items()}
    for sym,x in generated.items():x.to_csv(args.output/f"{sym}_legacy_signals.csv",index=False)
    windows=list(m["windows"])
    for year in range(2022,2027):
        windows.append(dict(name=f"annual_{year}",start=pd.Timestamp(f"{year}-01-01",tz="America/New_York").isoformat(),
                            end=min(pd.Timestamp(f"{year+1}-01-01",tz="America/New_York"),schedule.close_at.iloc[-1]).isoformat()))
    rows=[];daily={}
    for window in windows:
        start,end=pd.Timestamp(window["start"]),pd.Timestamp(window["end"])
        ss=select_window(schedule,start,end)
        for cost in ([10.] if window["name"].startswith("annual_") else [0.,5.,10.,20.]):
            sig={sym:x[(x.decision_at>=start)&(x.decision_at<=end)] if not x.empty else x for sym,x in generated.items()}
            t,e,c=eng.replay(inputs,schedule,sig,sectors,rules=rules,cost_bps=cost,prepared=cache,
                           trade_start=ss.open_at.iloc[0],trade_end=ss.close_at.iloc[-1],
                           max_holding_bars=3840,exit_on_daily_filter=False)
            name=f"{window['name']}_A_{int(cost)}bps"
            t.to_csv(args.output/f"{name}_trades.csv",index=False)
            e.to_csv(args.output/f"{name}_events.csv",index=False)
            daily[name]=daily_returns(c);daily[name].to_csv(args.output/f"{name}_daily.csv")
            if cost==10:c.to_csv(args.output/f"{name}_equity.csv",index=False)
            rows.append(dict(window=window["name"],arm="A",cost_bps=cost,**eng.metrics(t,c)))
        print(json.dumps({"A_window_completed":window["name"]}),flush=True)
    table=pd.DataFrame(rows);table.to_csv(args.output/"metrics.csv",index=False)
    old=pd.read_csv(args.primary/"metrics.csv")
    comparisons={};pvalues={};w="reused_holdout_2024_2026"
    q=daily_returns(pd.read_csv(args.primary/f"{w}_QQQ_BH_10bps_equity.csv"))
    returns={"A":daily[f"{w}_A_10bps"]}
    returns.update({a:daily_returns(pd.read_csv(args.primary/f"{w}_{a}_10bps_equity.csv")) for a in ["B","C","D","E"]})
    for arm in ["A","B","C","D","E"]:
        tab=table if arm=="A" else old
        weight=float(tab[(tab.window=="dev_2020_2021")&(tab.arm==arm)&(tab.cost_bps==10)].mean_gross_exposure.iloc[0])
        eq=(1-weight)*100000+weight*q.equity
        adjusted=eq.pct_change();adjusted.iloc[0]=eq.iloc[0]/100000-1
        for name,reference in [("QQQ_FULL",q["return"]),("QQQ_DEV_EXPOSURE_WEIGHT",adjusted)]:
            assert returns[arm].index.equals(reference.index)
            key=arm+"_minus_"+name
            comparisons[key]={str(k):block_test(returns[arm]["return"]-reference,k) for k in [20,60]}
            pvalues[key]=max(x["one_sided_null_bootstrap_p"] for x in comparisons[key].values())
        if arm!="A":
            key=arm+"_minus_A"
            comparisons[key]={str(k):block_test(returns[arm]["return"]-returns["A"]["return"],k) for k in [20,60]}
            pvalues[key]=max(x["one_sided_null_bootstrap_p"] for x in comparisons[key].values())
    result=dict(status="FIVE_ARM_RETROSPECTIVE_RESEARCH",A_identity="OWNER_CONFIRMED_ORIGINAL_S3_D1_H1_SRVP_CAUSAL_EXECUTION",
                A_rules=asdict(rules),max_holding_bars=3840,exit_on_daily_filter=False,
                comparisons=comparisons,holm14_adjusted_p=holm(pvalues),history_reused=True,untouched_oos=False,
                source_sha256=hashlib.sha256(args.module.read_bytes()).hexdigest(),
                baseline_source_sha256=hashlib.sha256(Path(__file__).resolve().parents[1].joinpath("src/services/strategy_lab/s3_legacy_baseline.py").read_bytes()).hexdigest(),
                manifest_sha256=ps["manifest_sha256"],TRADE_EXECUTION="NO",promotion="NO")
    (args.output/"statistics.json").write_text(json.dumps(result,indent=2))
    print(json.dumps({"completed":True,"A_cases":len(rows),"holm_family":len(pvalues)}),flush=True)


if __name__=="__main__":main()
