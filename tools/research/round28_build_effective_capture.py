from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pandas as pd

TFS=("D1","1H","15m","5m","1m")
COLS=("time_key","open","high","low","close","volume")
def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()
def bad_mask(df: pd.DataFrame) -> pd.Series:
    ohlc=df[["open","high","low","close"]]
    return ((ohlc<=0).any(axis=1) | (df.volume<0) |
            (df.high<df[["open","close","low"]].max(axis=1)) |
            (df.low>df[["open","close","high"]].min(axis=1)))
def main() -> int:
    ap=argparse.ArgumentParser(description="Create auditable effective bars by excluding whole contaminated dates.")
    ap.add_argument("--config",type=Path,required=True); ap.add_argument("--capture-root",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True); ap.add_argument("--symbols",help="comma-separated US symbols to process"); args=ap.parse_args()
    cfg=json.loads(args.config.read_text(encoding="utf-8-sig")); args.output_dir.mkdir(parents=True,exist_ok=True)
    summary=[]; missing=[]
    selected=set(args.symbols.split(",")) if args.symbols else None
    for item in cfg["markets"]["us"]["symbols"]:
        if selected is not None and item["symbol"] not in selected: continue
        symbol=item["symbol"]; files={}; dates=set(); invalid_by_tf={}
        for tf in TFS:
            name=f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv"
            raw=args.capture_root/name; quarantine=args.capture_root/"quarantine"/name
            src=raw if raw.is_file() else quarantine if quarantine.is_file() else None
            if src is None:
                missing.append({"symbol":symbol,"timeframe":tf}); continue
            df=pd.read_csv(src)
            df["time_key"]=pd.to_datetime(df["time_key"],errors="raise")
            for c in ("open","high","low","close","volume"): df[c]=pd.to_numeric(df[c],errors="raise")
            bad=bad_mask(df); invalid_dates=set(df.loc[bad,"time_key"].dt.date.astype(str))
            dates.update(invalid_dates); invalid_by_tf[tf]=int(bad.sum())
            files[tf]=(src,df,bad)
        excluded=sorted(dates); total_excluded=0
        for tf,(src,df,bad) in files.items():
            raw_rows=len(df); date_mask=df.time_key.dt.date.astype(str).isin(dates)
            clean=df.loc[~date_mask,COLS].copy().sort_values("time_key",kind="stable")
            if clean.empty or clean.time_key.duplicated().any(): raise ValueError(f"empty/duplicate effective data: {symbol}/{tf}")
            if bad_mask(clean).any() or not clean.time_key.is_monotonic_increasing: raise ValueError(f"effective QC failed: {symbol}/{tf}")
            out=args.output_dir/f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv"
            tmp=out.with_suffix(out.suffix+".tmp"); clean.to_csv(tmp,index=False); tmp.replace(out)
            removed=raw_rows-len(clean); total_excluded+=removed
            summary.append({"symbol":symbol,"sector":item["sector"],"timeframe":tf,"source_path":str(src),
              "source_sha256":sha(src),"raw_rows":raw_rows,"invalid_rows":invalid_by_tf[tf],
              "excluded_contaminated_date_rows":removed,"effective_rows":len(clean),
              "first":str(clean.time_key.iloc[0]),"last":str(clean.time_key.iloc[-1]),"effective_sha256":sha(out),
              "excluded_dates":excluded})
    report={"schema":"stock-razor-round28-effective-bars-v1","method":"For each symbol, detect OHLCV-invalid rows in any timeframe, exclude every bar for those calendar dates from all timeframes, then revalidate the remaining rows. Raw capture/quarantine files are never modified.","config_sha256":sha(args.config),"summary":summary,"missing":missing}
    (args.output_dir/"round28_effective_capture_manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"symbols_with_effective_data":len({r["symbol"] for r in summary}),"effective_files":len(summary),"missing_files":len(missing),"symbols_with_exclusions":len({r["symbol"] for r in summary if r["excluded_dates"]}),"excluded_dates_by_symbol":{s:next(r["excluded_dates"] for r in summary if r["symbol"]==s and r["excluded_dates"]) for s in sorted({r["symbol"] for r in summary if r["excluded_dates"]})}},ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
