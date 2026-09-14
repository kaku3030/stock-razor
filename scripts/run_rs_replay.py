#!/usr/bin/env python3
"""Research-only historical cross-sectional RS replay."""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(); p.add_argument('--input-dir',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--lookback',type=int,default=20); p.add_argument('--top-k',type=int,default=3); p.add_argument('--forward-bars',type=int,default=5); a=p.parse_args()
    series={}
    for f in a.input_dir.glob('*.csv'):
        if f.stem.endswith('_akshare'):
            continue
        with f.open(encoding='utf-8') as h: series[f.stem]=[(r['date'],float(r['close'])) for r in csv.DictReader(h)]
    dates=set.intersection(*(set(d for d,_ in v) for v in series.values())) if series else set(); dates=sorted(dates)
    rows=[]
    for i,d in enumerate(dates):
        ranked=[]
        for s,v in series.items():
            m={x:y for x,y in v}; prior=dates[i-a.lookback] if i>=a.lookback else None; future=dates[i+a.forward_bars] if i+a.forward_bars<len(dates) else None
            if prior and future and prior in m and future in m: ranked.append((m[d]/m[prior]-1,s,m[future]/m[d]-1))
        ranked.sort(reverse=True); rows.append({'as_of':d,'top': [{'symbol':s,'rs':r,'forward_return':fr} for r,s,fr in ranked[:a.top_k]]})
    result={'schema':'radar-rs-replay-v0.1','lookback':a.lookback,'top_k':a.top_k,'forward_bars':a.forward_bars,'rows':rows}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,indent=2),encoding='utf-8'); print(json.dumps({'status':'COMPUTED','dates':len(rows),'output':str(a.output)}))
if __name__=='__main__': main()
