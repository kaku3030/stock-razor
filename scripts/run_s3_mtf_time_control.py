#!/usr/bin/env python3
"""Supplemental E with matched observation horizon and shared known H4 ATR.

Import control module separately so prior primary source bytes stay intact.
Default B/E are replayed and compared to the sealed primary metrics first.
"""
import argparse
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


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--module",type=Path,required=True)
    ap.add_argument("--manifest",type=Path,required=True)
    ap.add_argument("--primary",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location("s3_control_engine",args.module)
    engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
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
    cache=engine.prepare_replay(inputs,schedule);rules=engine.Rules(**m.get("rules",{}))
    generated={name:{sym:engine.build_signals(x,schedule,arm,rules,prepared=cache,symbol=sym,matched_2h=matched)
                     for sym,x in inputs.items()}
               for name,arm,matched in [("B","B",False),("E","E",False),("E_TIME_MATCHED","E",True)]}
    prior=pd.read_csv(args.primary/"metrics.csv");rows=[];daily={};comparisons=[]
    for window in m["windows"]:
        start,end=pd.Timestamp(window["start"]),pd.Timestamp(window["end"])
        ss=select_window(schedule,start,end)
        for cost in [5.,10.,20.]:
            for name in ["B","E","E_TIME_MATCHED"]:
                sig={sym:x[(x.decision_at>=start)&(x.decision_at<=end)] if not x.empty else x
                     for sym,x in generated[name].items()}
                t,e,c=engine.replay(inputs,schedule,sig,sectors,rules=rules,cost_bps=cost,
                                   trade_start=ss.open_at.iloc[0],trade_end=ss.close_at.iloc[-1],prepared=cache)
                metric=engine.metrics(t,c)
                if name in ["B","E"]:
                    ref=prior[(prior.window==window["name"])&(prior.arm==name)&(prior.cost_bps==cost)].iloc[0]
                    for field in ["total_return","mdd","sharpe","profit_factor","win_rate","trades"]:
                        assert np.isclose(float(ref[field]),float(metric[field]),rtol=0,atol=1e-9),field
                    comparisons.append(dict(window=window["name"],arm=name,cost=cost,original_metrics_match=True))
                key=f"{window['name']}_{name}_{int(cost)}bps"
                t.to_csv(args.output/f"{key}_trades.csv",index=False)
                e.to_csv(args.output/f"{key}_events.csv",index=False)
                daily[key]=daily_returns(c);daily[key].to_csv(args.output/f"{key}_daily.csv")
                rows.append(dict(window=window["name"],arm=name,cost_bps=cost,**metric))
        print(json.dumps({"window_completed":window["name"]}),flush=True)
    pairs={};pv={}
    w="reused_holdout_2024_2026"
    for other in ["B","E"]:
        a=daily[f"{w}_E_TIME_MATCHED_10bps"]["return"]
        b=daily[f"{w}_{other}_10bps"]["return"]
        assert a.index.equals(b.index)
        key="E_TIME_MATCHED_minus_"+other
        pairs[key]={str(k):block_test(a-b,k) for k in [20,60]}
        pv[key]=max(x["one_sided_null_bootstrap_p"] for x in pairs[key].values())
    pd.DataFrame(rows).to_csv(args.output/"metrics.csv",index=False)
    result=dict(status="EXPLORATORY_REUSED_HISTORY",default_equivalence=comparisons,
                paired_tests=pairs,holm_adjusted_p=holm(pv),
                source_sha256=hashlib.sha256(args.module.read_bytes()).hexdigest(),
                manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                limitations="Observation horizons and volatility reference matched; stub sampling and setup event opportunities still differ.",
                TRADE_EXECUTION="NO",promotion="NO")
    (args.output/"statistics.json").write_text(json.dumps(result,indent=2))
    print(json.dumps({"completed":True,"cases":len(rows),"default_equivalence_cases":len(comparisons)}),flush=True)


if __name__=="__main__":main()
