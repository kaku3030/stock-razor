"""Frozen-rule postmortem and deterministic coverage-only expansion; no search.

Run against the existing offline Work03 directory. Round-one files are never
modified. Forward excursions are retrospective diagnostics, never signals.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(p, obj):
    Path(p).write_text(json.dumps(obj, indent=2, default=str, allow_nan=False), encoding="utf-8")


def split_legs(t, events, cost=.001):
    """Exact realized PnL attribution on each *observed* campaign path."""
    entries = events[events.reason.isin(["ENTRY", "ADD"])].copy()
    entries["time"] = pd.to_datetime(entries.time, utc=True)
    rows=[]
    for tr in t.to_dict("records"):
        begin, end = pd.Timestamp(tr["entry_at"]), pd.Timestamp(tr["exit_at"])
        first=entries[(entries.symbol==tr["symbol"]) & (entries.reason=="ENTRY") & (entries.time==begin)]
        if len(first)!=1: raise ValueError("ENTRY_EVENT_NOT_UNIQUE")
        later=entries[(entries.symbol==tr["symbol"]) & (entries.reason=="ENTRY") & (entries.time>begin)]
        limit=later.time.min() if len(later) else pd.Timestamp.max.tz_localize("UTC")
        legs=entries[(entries.symbol==tr["symbol"]) & (entries.time>=begin) & (entries.time<=end) & (entries.time<limit)]
        if int(legs.units.sum())!=int(tr["units"]): raise ValueError("LEG_UNITS_MISMATCH")
        if abs(float((legs.units*legs.price*(1+cost)).sum())-tr["cash_spent"])>1e-6: raise ValueError("LEG_CASH_MISMATCH")
        gross=float((legs.units*(tr["exit_price"]-legs.price)).sum())
        fees=float((legs.units*legs.price*cost).sum()+tr["units"]*tr["exit_price"]*cost)
        if abs(gross-fees-tr["net_pnl"])>1e-6: raise ValueError("PNL_ATTRIBUTION_MISMATCH")
        fg=float((first.units*(tr["exit_price"]-first.price)).sum())
        ff=float((first.units*(first.price+tr["exit_price"])*cost).sum())
        rows.append(dict(**tr,gross_pnl=gross,fees=fees,first_leg_net=fg-ff,
                         add_leg_net=tr["net_pnl"]-fg+ff,first_units=int(first.units.iloc[0]),
                         leg_count=len(legs)))
    return pd.DataFrame(rows)


def curve_stats(c, eng):
    x=c.copy(); x["end"]=pd.to_datetime(x.end,utc=True)
    return eng.metrics(pd.DataFrame(),x)


def simple_baseline(daily, start, end, cost_bps, trend):
    """Daily equal-dollar sleeves, 60% gross budget, integer long shares.

    Uses prior *closed* daily SMA200, executes next session OPEN, daily CLOSE
    MTM, final boundary liquidation. No stops/risk-budget/position-count match:
    this is a transparent simple capital benchmark, not equal-risk evidence.
    Sleeves receive 60%/N of initial cash; no cross-sleeve redistribution.
    """
    rate=cost_bps/10000; n=len(daily); outputs=[]; holdings=[]
    for sym,d in sorted(daily.items()):
        d=d.copy(); allowed=(d.close>d.close.rolling(200).mean()).shift(1,fill_value=False)
        x=d[(d.start>=start)&(d.end<=end)]
        cash=100000*.6/n; units=0; started=False; vals=[]; exposures=[]
        for idx,row in x.iterrows():
            want=bool(allowed.loc[idx]) if trend else True
            if not want and units: cash+=units*row.open*(1-rate);units=0
            if want and not units and (trend or not started):
                units=int(cash//(row.open*(1+rate)));cash-=units*row.open*(1+rate);started=True
            vals.append(cash+units*row.close);exposures.append(units*row.close)
        if units: vals[-1]-=units*x.iloc[-1].close*rate
        outputs.append(pd.Series(vals,index=pd.DatetimeIndex(x.end)))
        holdings.append(pd.Series(exposures,index=pd.DatetimeIndex(x.end)))
    equity=sum(outputs)+40000
    gross=sum(holdings)/equity;gross.iloc[-1]=0
    return pd.DataFrame(dict(end=equity.index,equity=equity.values,gross_exposure=gross.values))


def trade_diagnostics(t,e,source,cache,signals,schedule,qqqday):
    x=split_legs(t,e); rows=[]
    q=qqqday.copy(); q["s200"]=q.close.rolling(200).mean();q["lag20"]=q.s200.shift(20)
    for tr in x.to_dict("records"):
        sym=tr["symbol"];begin=pd.Timestamp(tr["entry_at"]);end=pd.Timestamp(tr["exit_at"])
        b=source[sym];d=cache.frames[sym,390];h=cache.frames[sym,60]
        risk=tr["initial_entry"]-tr["original_stop"]
        # Strictly before exit bar end avoids counting post-stop/target extremes.
        path=b[(b.end-pd.Timedelta(minutes=5)>=begin)&(b.end<end)]
        pre=d[d.available_at<begin];ph=h[h.available_at<begin]
        idx=int(d.start.searchsorted(begin,side="right")-1)
        row=dict(**tr,holding_sessions=int(schedule.close_at.searchsorted(end)-schedule.close_at.searchsorted(begin)+1),
                 first_leg_gross_R=(tr["exit_price"]-tr["initial_entry"])/risk,
                 mfe_lower_R=max(0,float((path.high.max()-tr["initial_entry"])/risk)) if len(path) else 0,
                 mae_lower_R=min(0,float((path.low.min()-tr["initial_entry"])/risk)) if len(path) else 0)
        for days in [1,5,20]:
            # Holding session+days at CLOSE; no next-session data beyond cutoff.
            j=idx+days
            row[f"forward_{days}d_R"]=(float(d.iloc[j].close)-tr["initial_entry"])/risk if j<len(d) else None
            row[f"forward_{days}d_return"]=(float(d.iloc[j].close)/tr["initial_entry"]-1) if j<len(d) else None
        sig=signals.get(sym,pd.DataFrame())
        hit=sig[sig.decision_at<begin] if len(sig) else sig
        if len(hit):
            s=hit.iloc[-1]; row["setup_to_entry_hours"]=(begin-pd.Timestamp(s.setup_end)).total_seconds()/3600
            row["signal_to_fill_bps"]=(tr["initial_entry"]/s.signal_close-1)*10000
        else: row.update(setup_to_entry_hours=None,signal_to_fill_bps=None)
        row["h1_distance_sma20_atr"]=(tr["initial_entry"]-ph.iloc[-1].sma20)/ph.iloc[-1].atr14 if len(ph) and ph.iloc[-1].atr14>0 else None
        pq=q[q.available_at<begin]
        qr=pq.iloc[-1] if len(pq) else None
        row["regime"]=("BELOW_200" if qr is None or qr.close<=qr.s200 else
                       "ABOVE_200_RISING" if qr.s200>qr.lag20 else "ABOVE_200_FLAT_FALLING")
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_trades(x):
    if x.empty:return dict(n=0,net=0.)
    net=float(x.net_pnl.sum());wins=x.net_pnl[x.net_pnl>0].sum();loss=-x.net_pnl[x.net_pnl<0].sum()
    sy=x.groupby("symbol").net_pnl.sum().sort_values(ascending=False)
    return dict(n=len(x),net=net,gross=float(x.gross_pnl.sum()),fees=float(x.fees.sum()),
                first_leg_net=float(x.first_leg_net.sum()),add_leg_net=float(x.add_leg_net.sum()),
                added=int(x.added.sum()),pf=float(wins/loss) if loss else None,
                win_rate=float((x.net_pnl>0).mean()),stop_fraction=float(x.exit_reason.isin(["STOP","GAP_STOP"]).mean()),
                stopped_within_2_sessions=int(((x.holding_sessions<=2)&x.exit_reason.isin(["STOP","GAP_STOP"])).sum()),
                losers_reached_1R_lower=int(((x.net_pnl<0)&(x.mfe_lower_R>=1)).sum()),
                losers=int((x.net_pnl<0).sum()),median_mfe_R=float(x.mfe_lower_R.median()),
                mean_actual_first_gross_R=float(x.first_leg_gross_R.mean()),
                mean_forward_5d_R=float(x.forward_5d_R.dropna().mean()) if x.forward_5d_R.notna().any() else None,
                mean_forward_20d_R=float(x.forward_20d_R.dropna().mean()) if x.forward_20d_R.notna().any() else None,
                mean_forward_5d_return=float(x.forward_5d_return.dropna().mean()) if x.forward_5d_return.notna().any() else None,
                mean_forward_20d_return=float(x.forward_20d_return.dropna().mean()) if x.forward_20d_return.notna().any() else None,
                net_excluding_best_5_trades=float(net-x.net_pnl.nlargest(5).sum()),
                best_symbol=str(sy.index[0]),net_excluding_best_symbol=float(net-sy.iloc[0]),
                median_entry_extension_atr=float(x.h1_distance_sma20_atr.median()),
                median_setup_delay_hours=float(x.setup_to_entry_hours.median()))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,required=True);ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--engine",type=Path,required=True)
    args=ap.parse_args(); root=args.root.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    begun=time.perf_counter();sys.path.insert(0,str(root))
    from scripts.run_s3_mtf_research import load_bars,select_window
    from scripts.run_s3_mtf_validation import daily_returns,block_test
    from src.services.strategy_lab.s3_legacy_baseline import build_legacy_signals
    spec=importlib.util.spec_from_file_location("round2_frozen_engine",args.engine)
    eng=importlib.util.module_from_spec(spec);sys.modules[spec.name]=eng;spec.loader.exec_module(eng)
    if sha(args.engine)!="b666aa1d9f85c25ba1df5bd326b305a205852748b16dce0786d5f38f5a3a64aa":raise ValueError("FROZEN_ENGINE_MISMATCH")
    old=json.loads((root/"core8_manifest.json").read_text());audit=json.loads((root/"raw_input_audit.json").read_text())
    core=set(x["symbol"] for x in old["symbols"])
    good=[x for x in audit if x["rows"]==152262 and all(x[k]==0 for k in ["missing","off_grid","bad_ohlcv","duplicates"]) and x["hash_match"]]
    extra=sorted([x for x in good if x["symbol"] not in core],key=lambda x:x["symbol"])
    prereg=dict(selection="ALL_NON_CORE8_IN_EXISTING60_WITH_IDENTICAL_COMPLETE2019_2026_GRID; NO_RETURN_SELECTION",
                expanded=[x["symbol"] for x in extra],core8=sorted(core),independent=[],
                history_reused=True,untouched_oos=False,costs_bps=[0,10],windows=old["windows"],
                tests="No rerun of original125",engine_sha256=sha(args.engine),runner_sha256=sha(__file__),
                arms=["A","B","C","D","E"],extra_policy="B_NO_ADD_FULL_RISK only; existing round1 policy",
                benchmarks="fixed60percent equal sleeves BH / prior closed D1 close>SMA200; not risk or position-count matched",
                diagnostic_only="forward1/5/20day outcomes, excursions and cohort regimes NEVER used in signals",
                TRADE_EXECUTION="NO",promotion="NO")
    dump(out/"preregistered_plan.json",prereg)
    frozen=[]
    for sub in ["primary_v01","legacy_A_v01","validation_v02","time_control_v01"]:
        for p in sorted((root/sub).glob("*")):
            if p.is_file():frozen.append(dict(path=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=sha(p)))
    for name in ["core8_manifest.json","schedule.csv","raw_input_audit.json","legacy_equivalence.json","S3_CORE8_Evidence_20261024.zip"]:
        p=root/name;frozen.append(dict(path=name,bytes=p.stat().st_size,sha256=sha(p)))
    dump(out/"round1_freeze.json",dict(files=frozen,rule_commit="b7f51f3e72d2d0584314d139cbfbbc54760960d5",merge_commit="6ff0b9ae29e85db9e9ac919e86624b26097463c6"))
    sp=root/old["schedule"]["path"]
    if sha(sp)!=old["schedule"]["sha256"]:raise ValueError("SCHEDULE_HASH_MISMATCH")
    schedule=pd.read_csv(sp)
    for c in ["open_at","close_at"]:schedule[c]=pd.to_datetime(schedule[c],utc=True)
    items=list(old["symbols"])
    for a in extra:items.append({**old["symbols"][0],"symbol":a["symbol"],"sector":a["sector"],"path":a["path"],"sha256":a["sha256"]})
    source={x["symbol"]:load_bars(x,root) for x in items};sectors={x["symbol"]:x["sector"] for x in items}
    cache=eng.prepare_replay(source,schedule)
    qqq=load_bars(old["benchmark"],root);qqqday=eng.features(eng.aggregate(qqq,schedule,390))
    rule=eng.Rules(); arule=eng.Rules(first_risk_fraction=1.,max_sessions=1000000)
    signals={a:{s:(build_legacy_signals(b,schedule,prepared=cache,symbol=s) if a=="A" else
                    eng.build_signals(b,schedule,a,rule,prepared=cache,symbol=s)) for s,b in source.items()} for a in "ABCDE"}
    for a,ss in signals.items():
        for s,x in ss.items():x.to_csv(out/f"signals_{a}_{s}.csv",index=False)
    print(json.dumps(dict(stage="frozen_and_loaded",expanded=len(extra),freeze_files=len(frozen))),flush=True)
    summaries=[];regimes=[];symbolrows=[];exits=[];full_diags=[];metrics=[];daily_results={}
    # Reuse existing CORE8 ledgers; do not repeat old performance replay.
    for w in old["windows"]:
        for a in "ABCDE":
            p=root/("legacy_A_v01" if a=="A" else "primary_v01")/f"{w['name']}_{a}_10bps"
            t=pd.read_csv(str(p)+"_trades.csv");e=pd.read_csv(str(p)+"_events.csv")
            diag=trade_diagnostics(t,e,source,cache,signals[a],schedule,qqqday)
            diag.to_csv(out/f"CORE8_{w['name']}_{a}_diagnostics.csv",index=False)
            summaries.append(dict(pool="CORE8",window=w["name"],arm=a,**summarize_trades(diag)))
            if w["name"]=="full_2020_2026":full_diags.append(diag.assign(pool="CORE8"))
            for key,group in diag.groupby("regime"):regimes.append(dict(pool="CORE8",window=w["name"],arm=a,regime=key,**summarize_trades(group)))
            for key,group in diag.groupby("symbol"):symbolrows.append(dict(pool="CORE8",window=w["name"],arm=a,symbol=key,net=float(group.net_pnl.sum()),trades=len(group)))
            for key,group in diag.groupby("exit_reason"):exits.append(dict(pool="CORE8",window=w["name"],arm=a,reason=key,n=len(group),net=float(group.net_pnl.sum())))
            c=pd.read_csv(str(p)+"_equity.csv");daily_results["CORE8",w["name"],a]=daily_returns(c)
    # Coverage-only 33-name expansion: independent from CORE8 symbols, reused history.
    exsym=[x["symbol"] for x in extra];inputs={s:source[s] for s in exsym};sect={s:sectors[s] for s in exsym}
    ec=eng.prepare_replay(inputs,schedule)
    for w in old["windows"]:
        ss=select_window(schedule,pd.Timestamp(w["start"]),pd.Timestamp(w["end"]))
        left,right=ss.open_at.iloc[0],ss.close_at.iloc[-1]
        for cost in [0.,10.]:
            for a in list("ABCDE")+(["B_NO_ADD_FULL_RISK"] if cost==10 else []):
                base=a[0]; rr=arule if a=="A" else replace(rule,first_risk_fraction=1.) if a.startswith("B_NO") else rule
                sig={s:x[(x.decision_at>=left)&(x.decision_at<=right)] if len(x) else x for s,x in signals[base].items() if s in inputs}
                kw=dict(max_holding_bars=3840,exit_on_daily_filter=False) if a=="A" else {}
                t,e,c=eng.replay(inputs,schedule,sig,sect,rules=rr,cost_bps=cost,prepared=ec,trade_start=left,trade_end=right,**kw)
                name=f"EXP33_{w['name']}_{a}_{int(cost)}bps"
                t.to_csv(out/f"{name}_trades.csv",index=False);e.to_csv(out/f"{name}_events.csv",index=False)
                dr=daily_returns(c);dr.to_csv(out/f"{name}_daily.csv")
                metrics.append(dict(pool="EXP33",window=w["name"],arm=a,cost_bps=cost,**eng.metrics(t,c)))
                if cost==10:
                    daily_results["EXP33",w["name"],a]=dr
                    diag=trade_diagnostics(t,e,source,cache,signals[base],schedule,qqqday)
                    diag.to_csv(out/f"{name}_diagnostics.csv",index=False)
                    summaries.append(dict(pool="EXP33",window=w["name"],arm=a,**summarize_trades(diag)))
                    for key,g in diag.groupby("regime"):regimes.append(dict(pool="EXP33",window=w["name"],arm=a,regime=key,**summarize_trades(g)))
                    for key,g in diag.groupby("symbol"):symbolrows.append(dict(pool="EXP33",window=w["name"],arm=a,symbol=key,net=float(g.net_pnl.sum()),trades=len(g)))
                    for key,g in diag.groupby("exit_reason"):exits.append(dict(pool="EXP33",window=w["name"],arm=a,reason=key,n=len(g),net=float(g.net_pnl.sum())))
        print(json.dumps(dict(stage="expanded_window_done",window=w["name"])),flush=True)
    # Capital and clock matched simple reference portfolios; explicit risk mismatch.
    paired={}
    for pool,syms in [("CORE8",sorted(core)),("EXP33",exsym)]:
        daily={s:cache.frames[s,390] for s in syms}
        for w in old["windows"]:
            ss=select_window(schedule,pd.Timestamp(w["start"]),pd.Timestamp(w["end"]))
            for cost in [0.,10.]:
                for name,trend in [("EW_BH60",False),("EW_D1_SMA200_60",True)]:
                    c=simple_baseline(daily,ss.open_at.iloc[0],ss.close_at.iloc[-1],cost,trend)
                    metrics.append(dict(pool=pool,window=w["name"],arm=name,cost_bps=cost,**curve_stats(c,eng)))
                    dr=daily_returns(c);dr.to_csv(out/f"{pool}_{w['name']}_{name}_{int(cost)}bps_daily.csv")
                    if cost==10:
                        for a in "ABCDE":
                            ad=daily_results[pool,w["name"],a]
                            if not ad.index.equals(dr.index):raise ValueError("PAIRED_DAY_MISMATCH")
                            if w["name"]=="reused_holdout_2024_2026":
                                paired[f"{pool}_{a}_minus_{name}"]={str(k):block_test(ad["return"]-dr["return"],k) for k in [20,60]}
    # Reuse the pre-existing full-budget no-add counterfactual for CORE8 B.
    for w in old["windows"]:
        if w["name"]=="full_2020_2026":continue
        candidates=list((root/"validation_v02").glob(f"*NO_ADD*{w['name']}*daily.csv"))
        if len(candidates)!=1:raise ValueError("EXISTING_NO_ADD_EQUITY_NOT_UNIQUE:"+str(candidates))
        d=pd.read_csv(candidates[0],index_col=0);d.index=pd.Index(pd.to_datetime(d.index).date)
        b=daily_results["CORE8",w["name"],"B"]
        if not b.index.equals(d.index):raise ValueError("NO_ADD_DAYS_MISMATCH")
        paired["CORE8_B_minus_NO_ADD_"+w["name"]]={str(k):block_test(b["return"]-d["return"],k) for k in [20,60]}
    for w in old["windows"]:
        b=daily_results["EXP33",w["name"],"B"];d=daily_results["EXP33",w["name"],"B_NO_ADD_FULL_RISK"]
        paired["EXP33_B_minus_NO_ADD_"+w["name"]]={str(k):block_test(b["return"]-d["return"],k) for k in [20,60]}
    pd.DataFrame(summaries).to_csv(out/"campaign_summary.csv",index=False)
    pd.DataFrame(regimes).to_csv(out/"entry_regime_summary.csv",index=False)
    pd.DataFrame(symbolrows).to_csv(out/"symbol_contributions.csv",index=False)
    pd.DataFrame(exits).to_csv(out/"exit_contributions.csv",index=False)
    pd.DataFrame(metrics).to_csv(out/"new_metrics.csv",index=False)
    dump(out/"paired_statistics.json",paired)
    coverage=[]
    for pool,syms in [("CORE8",sorted(core)),("EXP33",exsym)]:
        for w in old["windows"]:
            for label in ["ORIGINAL_D1_20_50","CANDIDATE_D1_50_200"]:
                buckets={True:[],False:[]}
                for s in syms:
                    d=cache.frames[s,390]
                    state=((d.close>d.sma20)&(d.sma20>d.sma50)) if label.startswith("ORIGINAL") else ((d.close>d.sma50)&(d.sma50>d.sma200))
                    mask=(d.start>=pd.Timestamp(w["start"]))&(d.end<=pd.Timestamp(w["end"]))
                    for flag in [True,False]:
                        ix=mask&(state.shift(1,fill_value=False)==flag)
                        buckets[flag].append(pd.DataFrame({"r1":d.close/d.open-1,"r5":d.close.shift(-5)/d.open-1,"r20":d.close.shift(-20)/d.open-1})[ix])
                for flag,rows in buckets.items():
                    z=pd.concat(rows)
                    coverage.append(dict(pool=pool,window=w["name"],filter=label,allowed=flag,stock_days=len(z),
                                         mean_next_session=float(z.r1.mean()),mean_5d=float(z.r5.mean()),mean_20d=float(z.r20.mean())))
    pd.DataFrame(coverage).to_csv(out/"direction_filter_diagnostics.csv",index=False)
    # Recheck freeze after computation; output directory is separate and immutable.
    for f in frozen:
        if sha(root/f["path"])!=f["sha256"]:raise ValueError("ROUND1_MUTATED")
    dump(out/"completion.json",dict(status="COMPLETE_RETROSPECTIVE_ONLY",elapsed_seconds=time.perf_counter()-begun,
                independent_validation="UNAVAILABLE_NO_UNSEEN_HISTORY_OR_PIT_POOL",engine_sha256=sha(args.engine),
                runner_sha256=sha(__file__),new_cases=len(metrics),round1_freeze_verified=True,TRADE_EXECUTION="NO",promotion="NO"))
    files=[dict(path=str(p.relative_to(out)),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(out.glob("*")) if p.is_file()]
    dump(out/"artifact_manifest.json",files)
    print(json.dumps(dict(status="COMPLETE",seconds=time.perf_counter()-begun,new_cases=len(metrics))),flush=True)


if __name__=="__main__":main()
