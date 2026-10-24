"""Correct the residual-integer-share add contamination without rewriting R1.

One hash-pinned engine expression is disabled in a derived, separately named
research runtime. R1 files and main ABCDE evidence are never overwritten.
"""
import argparse
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pandas as pd
from run_s3_round2 import sha,dump,trade_diagnostics,summarize_trades


def strict_engine(path):
    source=Path(path).read_text(encoding="utf-8")
    # The merged snapshot differs only in adapter status/error wording.
    if sha(path) not in {"b666aa1d9f85c25ba1df5bd326b305a205852748b16dce0786d5f38f5a3a64aa",
                         "5f7d7e5972be4a0683a486584adde3c1cdeefa14af1745602b02967a922a41c5"}:
        raise ValueError("FROZEN_ENGINE_MISMATCH")
    before='if (not p["added"] and math.isfinite(hour.atr14)'
    after='if (False and not p["added"] and math.isfinite(hour.atr14)'
    if source.count(before)!=1:raise ValueError("STRICT_NO_ADD_PATCH_NOT_UNIQUE")
    source=source.replace(before,after)
    module=types.ModuleType("s3_strict_no_add");module.__file__=str(path);sys.modules[module.__name__]=module
    exec(compile(source,str(path),"exec"),module.__dict__)
    return module,source


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ['root','primary','output','engine']:ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(exist_ok=False);root=a.root.resolve();sys.path.insert(0,str(root))
    from scripts.run_s3_mtf_research import load_bars,select_window
    from scripts.run_s3_mtf_validation import daily_returns,block_test
    eng,derived=strict_engine(a.engine)
    plan=json.loads((a.primary/'preregistered_plan.json').read_text())
    dump(a.output/'correction_plan.json',dict(reason='first_risk_fraction=1 does not forbid residual rounding adds',
       original_results_untouched=True,patch='One H1 add-queue conditional disabled; all signal, stop, fill, cost logic unchanged',
       derived_sha256=hashlib.sha256(derived.encode()).hexdigest(),runner_sha256=sha(__file__),
       controls=['STRICT_A','B_STRICT_FIRST100','B_STRICT_FIRST40'],costs_A=[0,10],costs_B=[10],history_reused=True,promotion='NO'))
    old=json.loads((root/'core8_manifest.json').read_text());audit=json.loads((root/'raw_input_audit.json').read_text())
    its=list(old['symbols']);wanted=set(plan['expanded'])
    its += [{**old['symbols'][0],'symbol':v['symbol'],'sector':v['sector'],'path':v['path'],'sha256':v['sha256']} for v in audit if v['symbol'] in wanted]
    schedule=pd.read_csv(root/old['schedule']['path'])
    if sha(root/old['schedule']['path'])!=old['schedule']['sha256']:raise ValueError('SCHEDULE_HASH_MISMATCH')
    for c in ['open_at','close_at']:schedule[c]=pd.to_datetime(schedule[c],utc=True)
    source={i['symbol']:load_bars(i,root) for i in its};sectors={i['symbol']:i['sector'] for i in its}
    cache=eng.prepare_replay(source,schedule)
    q=load_bars(old['benchmark'],root);qd=eng.features(eng.aggregate(q,schedule,390))
    sigs={}
    for arm in ['A','B']:
        sigs[arm]={}
        for sym in source:
            x=pd.read_csv(a.primary/f'signals_{arm}_{sym}.csv')
            for c in ['decision_at','signal_end','setup_end','d1_end','structure_end']:x[c]=pd.to_datetime(x[c],utc=True)
            sigs[arm][sym]=x
    rows=[];summ=[];pairs={};reg=[]
    for pool,syms in [('CORE8',plan['core8']),('EXP33',plan['expanded'])]:
        inp={s:source[s] for s in syms};sect={s:sectors[s] for s in syms};pc=eng.prepare_replay(inp,schedule)
        for w in old['windows']:
            ss=select_window(schedule,pd.Timestamp(w['start']),pd.Timestamp(w['end']));left,right=ss.open_at.iloc[0],ss.close_at.iloc[-1]
            policies=[('B_STRICT_FIRST100','B',1.),('B_STRICT_FIRST40','B',.4)]+([('STRICT_A','A',1.)] if pool=='EXP33' else [])
            for name,arm,fraction in policies:
                for cost in ([0.,10.] if arm=='A' else [10.]):
                    rr=eng.Rules(first_risk_fraction=fraction,max_sessions=1000000 if arm=='A' else 50)
                    sig={s:x[(x.decision_at>=left)&(x.decision_at<=right)] if len(x) else x for s,x in sigs[arm].items() if s in inp}
                    kw=dict(max_holding_bars=3840,exit_on_daily_filter=False) if arm=='A' else {}
                    t,e,c=eng.replay(inp,schedule,sig,sect,rules=rr,cost_bps=cost,prepared=pc,trade_start=left,trade_end=right,**kw)
                    if len(e[e.reason=='ADD']):raise ValueError('STRICT_NO_ADD_VIOLATED')
                    pre=f'{pool}_{w["name"]}_{name}_{int(cost)}bps'
                    t.to_csv(a.output/(pre+'_trades.csv'),index=False);e.to_csv(a.output/(pre+'_events.csv'),index=False)
                    d=daily_returns(c);d.to_csv(a.output/(pre+'_daily.csv'))
                    rows.append(dict(pool=pool,window=w['name'],arm=name,cost_bps=cost,**eng.metrics(t,c)))
                    if cost==10:
                        z=trade_diagnostics(t,e,source,cache,sigs[arm],schedule,qd);z.to_csv(a.output/(pre+'_diagnostics.csv'),index=False)
                        summ.append(dict(pool=pool,window=w['name'],arm=name,**summarize_trades(z)))
                        for key,g in z.groupby('regime'):reg.append(dict(pool=pool,window=w['name'],arm=name,regime=key,**summarize_trades(g)))
                        if arm=='B':
                            p=(root/'primary_v01'/f'{w["name"]}_B_10bps_equity.csv') if pool=='CORE8' else a.primary/f'EXP33_{w["name"]}_B_10bps_daily.csv'
                            b=daily_returns(pd.read_csv(p)) if pool=='CORE8' else pd.read_csv(p,index_col=0)
                            if pool=='EXP33':b.index=pd.Index(pd.to_datetime(b.index).date)
                            if not b.index.equals(d.index):raise ValueError('DAY_INDEX_MISMATCH')
                            pairs[f'{pool}_{w["name"]}_B_minus_{name}']={str(k):block_test(b['return']-d['return'],k) for k in [20,60]}
            print(json.dumps(dict(pool=pool,window=w['name'],completed=True)),flush=True)
    pd.DataFrame(rows).to_csv(a.output/'metrics.csv',index=False);pd.DataFrame(summ).to_csv(a.output/'campaign_summary.csv',index=False)
    pd.DataFrame(reg).to_csv(a.output/'regime_summary.csv',index=False);dump(a.output/'paired_statistics.json',pairs)
    dump(a.output/'completion.json',dict(status='COMPLETE',cases=len(rows),no_add_events_verified=True,runner_sha256=sha(__file__),derived_engine_sha256=hashlib.sha256(derived.encode()).hexdigest(),promotion='NO'))
    print(json.dumps(dict(status='COMPLETE',cases=len(rows))),flush=True)


if __name__=='__main__':main()
