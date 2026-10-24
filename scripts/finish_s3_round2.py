"""Ledger-only comparison, scale controls and export. No strategy reruns."""
import argparse
import base64
import json
from pathlib import Path
import sys
import zipfile
import pandas as pd
from run_s3_round2 import sha,dump,curve_stats


def main():
    ap=argparse.ArgumentParser()
    for k in ['root','primary','strict','output']:ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(exist_ok=False);sys.path.insert(0,str(a.root))
    from scripts.run_s3_mtf_validation import block_test,holm,daily_returns
    from src.services.strategy_lab import s3_mtf as eng
    mm=pd.read_csv(a.primary/'new_metrics.csv');sm=pd.read_csv(a.strict/'metrics.csv')
    oldm=pd.concat([pd.read_csv(a.root/'primary_v01/metrics.csv'),pd.read_csv(a.root/'legacy_A_v01/metrics.csv')])
    rows=[];comparisons={};pvalues={}
    dev='dev_2020_2021';hold='reused_holdout_2024_2026'
    def read_daily(p):
        x=pd.read_csv(p,index_col=0);x.index=pd.Index(pd.to_datetime(x.index).date);return x
    for pool in ['CORE8','EXP33']:
        for arm in 'ABCDE':
            def strategy(w):
                if pool=='CORE8':
                    p=a.root/('legacy_A_v01' if arm=='A' else 'primary_v01')/f'{w}_{arm}_10bps_equity.csv'
                    return daily_returns(pd.read_csv(p))
                p=a.strict/f'EXP33_{w}_STRICT_A_10bps_daily.csv' if arm=='A' else a.primary/f'EXP33_{w}_{arm}_10bps_daily.csv'
                return read_daily(p)
            tab=oldm if pool=='CORE8' else sm[sm.arm=='STRICT_A'].assign(arm='A') if arm=='A' else mm
            q=tab[(tab.window==dev)&(tab.arm==arm)&(tab.cost_bps==10)]
            if pool=='EXP33' and arm!='A':q=q[q.pool=='EXP33']
            exposure=float(q.mean_gross_exposure.iloc[0]); sd=strategy(dev)['return'].std()
            actual=strategy(hold)
            for base in ['EW_BH60','EW_D1_SMA200_60']:
                bd=read_daily(a.primary/f'{pool}_{dev}_{base}_10bps_daily.csv')
                bh=read_daily(a.primary/f'{pool}_{hold}_{base}_10bps_daily.csv')
                bdev=mm[(mm.pool==pool)&(mm.window==dev)&(mm.arm==base)&(mm.cost_bps==10)]
                for kind,w in [('DEV_EXPOSURE',exposure/float(bdev.mean_gross_exposure.iloc[0])),('DEV_VOLATILITY',sd/bd['return'].std())]:
                    if not 0<=w<=1:raise ValueError('UNEXPECTED_LEVERAGE_REQUIREMENT')
                    eq=(1-w)*100000+w*bh.equity
                    ret=eq.pct_change();ret.iloc[0]=eq.iloc[0]/100000-1
                    if not ret.index.equals(actual.index):raise ValueError('PAIRED_DAYS_MISMATCH')
                    # Daily-only statistics; do not label MDD as5m close.
                    peak=pd.concat([pd.Series([100000.]),eq.reset_index(drop=True)]).cummax().iloc[1:].values
                    name=f'{pool}_{arm}_minus_{base}_{kind}'
                    comparisons[name]={str(k):block_test(actual['return']-ret,k) for k in [20,60]}
                    pvalues[name]=max(v['one_sided_null_bootstrap_p'] for v in comparisons[name].values())
                    rows.append(dict(pool=pool,arm=arm,baseline=base,scale=kind,dev_weight=w,
                        baseline_hold_return=float(eq.iloc[-1]/100000-1),strategy_hold_return=float(actual.equity.iloc[-1]/100000-1),
                        baseline_daily_mdd=float((1-eq.values/peak).max()),baseline_daily_sharpe=float(ret.mean()/ret.std()*252**.5)))
    pd.DataFrame(rows).to_csv(a.output/'scaled_benchmark_metrics.csv',index=False)
    dump(a.output/'scaled_benchmark_statistics.json',dict(comparisons=comparisons,holm40=holm(pvalues),
         caution='Static cash + underlying benchmark; development calibration only; future volatility/exposure NOT exactly matched. Reused history; descriptive inferential controls, not independent efficacy proof.'))
    funnel=[]
    plan=json.loads((a.primary/'preregistered_plan.json').read_text())
    for pool,syms in [('CORE8',plan['core8']),('EXP33',plan['expanded'])]:
        for arm in 'ABCDE':
            counts=sum(len(pd.read_csv(a.primary/f'signals_{arm}_{s}.csv')) for s in syms)
            p=a.root/('legacy_A_v01' if arm=='A' else 'primary_v01')/f'{hold}_{arm}_10bps_events.csv' if pool=='CORE8' else a.strict/f'EXP33_{hold}_STRICT_A_10bps_events.csv' if arm=='A' else a.primary/f'EXP33_{hold}_{arm}_10bps_events.csv'
            events=pd.read_csv(p)
            funnel.append(dict(pool=pool,arm=arm,full_snapshot_signals=counts,hold_event_counts=events.reason.value_counts().to_dict()))
    dump(a.output/'execution_funnel.json',funnel)
    # No source code duplication in the user evidence archive; source is Git-backed.
    target=a.output/'S3_Round2_Evidence_20261024.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for label,d in [('round2',a.primary),('strict',a.strict),('final',a.output)]:
            for p in sorted(d.glob('*')):
                if p.is_file() and (p.suffix=='.json' or (p.suffix=='.csv' and not p.name.startswith('signals_') and not p.name.endswith(('_events.csv','_daily.csv','_trades.csv')))):
                    z.write(p,label+'/'+p.name)
    b=base64.b64encode(target.read_bytes()).decode('ascii')
    chunks=[]
    for i in range(0,len(b),50000):
        p=a.output/f'export_{i//50000:03}.txt';p.write_text(b[i:i+50000],encoding='ascii');chunks.append(p.name)
    dump(a.output/'export_receipt.json',dict(archive=target.name,bytes=target.stat().st_size,sha256=sha(target),chunks=chunks))
    print(json.dumps(dict(status='COMPLETE',archive_bytes=target.stat().st_size,sha256=sha(target),chunks=chunks)),flush=True)


if __name__=='__main__':main()
