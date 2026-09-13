#!/usr/bin/env python3
"""Summarize historical RS replay into auditable split metrics."""
import argparse, json
from pathlib import Path

def summarize(rows, top_k):
    values=[x['forward_return'] for row in rows for x in row['top'][:top_k]]
    return {'observations':len(values),'average_forward_return':sum(values)/len(values) if values else 0.0,'win_rate':sum(v>0 for v in values)/len(values) if values else 0.0}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--input',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    data=json.loads(a.input.read_text(encoding='utf-8')); rows=data.get('rows',[]); c1=len(rows)//3; c2=2*len(rows)//3
    result={'schema':'radar-rs-summary-v0.1','source':str(a.input),'splits':{},'top_k':{}}
    for name,part in [('development',rows[:c1]),('validation',rows[c1:c2]),('never_seen_holdout',rows[c2:])]: result['splits'][name]=summarize(part, data.get('top_k',3))
    for k in (1,3,5): result['top_k'][str(k)]=summarize(rows,k)
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,indent=2,sort_keys=True),encoding='utf-8'); print(json.dumps({'status':'SUMMARIZED','output':str(a.output),'summary':result}, sort_keys=True))
if __name__=='__main__': main()
