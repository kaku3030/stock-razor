#!/usr/bin/env python
"""Capture US QFQ/RTH OHLCV from an already-running local Futu/OpenD. Read-only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from futu import AuType, KLType, KL_FIELD, OpenQuoteContext, Session

TIMEFRAMES = {
    "D1": KLType.K_DAY,
    "1H": KLType.K_60M,
    "15m": KLType.K_15M,
    "5m": KLType.K_5M,
    "1m": KLType.K_1M,
}
COLUMNS = ["time_key", "open", "high", "low", "close", "volume"]


def atomic_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def capture_one(ctx, code: str, symbol: str, timeframe: str, start: str, end: str,
                output_dir: Path, page_size: int, max_pages: int | None, force: bool) -> dict:
    target = output_dir / f"US_{symbol}_{timeframe}_qfq_rth_{start.replace('-', '')}_{end.replace('-', '')}.csv"
    state_dir = output_dir / ".capture_state" / f"{symbol}_{timeframe}"
    pages_dir = state_dir / "pages"
    state_path = state_dir / "checkpoint.json"
    if target.exists() and not force:
        return {"symbol": symbol, "timeframe": timeframe, "status": "ALREADY_PRESENT",
                "path": str(target), "bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    state_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    contract = {"code": code, "symbol": symbol, "timeframe": timeframe,
                "start": start, "end": end, "page_size": page_size,
                "adjustment": "QFQ", "session": "RTH"}
    if state_path.exists() and not force:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("contract") != contract:
            raise ValueError(f"checkpoint contract mismatch: {state_path}")
        page_no = int(state["completed_pages"])
        cursor_b64 = state.get("next_page_key_b64")
        page_key = base64.b64decode(cursor_b64) if cursor_b64 else None
        if state.get("complete"):
            quarantine = output_dir / "quarantine" / target.name
            if quarantine.exists():
                raise ValueError(f"captured bars failed quality validation; immutable quarantine file: {quarantine}")
            raise ValueError(f"completed checkpoint has no final file: {state_path}")
        if page_key is not None:
            # OpenD page keys are context-scoped. A restarted process must restart
            # this symbol/timeframe from page one rather than reuse a stale token.
            for old in pages_dir.glob("page_*.csv"):
                old.unlink()
            page_no, page_key = 0, None
            atomic_json(state_path, {"contract": contract, "completed_pages": 0,
                                     "next_page_key_b64": None, "complete": False,
                                     "restart_reason": "OpenD cursor is context-scoped"})
            print(f"[capture] restarting {symbol}/{timeframe} from page one after process restart",
                  flush=True)
    else:
        for old in pages_dir.glob("page_*.csv"):
            old.unlink()
        page_no, page_key = 0, None
        atomic_json(state_path, {"contract": contract, "completed_pages": 0,
                                 "next_page_key_b64": None, "complete": False})
    started = time.perf_counter()
    while True:
        if max_pages is not None and page_no >= max_pages:
            return {"symbol": symbol, "timeframe": timeframe, "status": "PARTIAL_CHECKPOINT",
                    "pages": page_no, "next_page_key_present": page_key is not None,
                    "elapsed_seconds": round(time.perf_counter() - started, 2)}
        ret, frame, next_key = ctx.request_history_kline(
            code, start=start, end=end, ktype=TIMEFRAMES[timeframe],
            autype=AuType.QFQ, fields=[KL_FIELD.ALL], max_count=page_size,
            page_req_key=page_key, session=Session.RTH,
        )
        if ret != 0:
            raise RuntimeError(f"OpenD request failed for {code}/{timeframe}: {frame}")
        if frame is None or frame.empty:
            if page_no == 0:
                raise RuntimeError(f"OpenD returned no bars for {code}/{timeframe} in {start}..{end}")
            if next_key is not None:
                raise RuntimeError(f"OpenD returned an empty page with a continuation key for {code}/{timeframe}")
            break
        missing = set(COLUMNS) - set(frame.columns)
        if missing:
            raise ValueError(f"OpenD response missing required columns: {sorted(missing)}")
        page_no += 1
        page_path = pages_dir / f"page_{page_no:06d}.csv"
        frame[COLUMNS].to_csv(page_path, index=False)
        if next_key is not None and not isinstance(next_key, bytes):
            raise TypeError(f"unexpected page cursor type: {type(next_key).__name__}")
        cursor_b64 = base64.b64encode(next_key).decode("ascii") if next_key else None
        atomic_json(state_path, {"contract": contract, "completed_pages": page_no,
                                 "next_page_key_b64": cursor_b64, "complete": next_key is None})
        page_key = next_key
        if page_no % 25 == 0 or next_key is None:
            print(f"[capture] {symbol}/{timeframe}: pages={page_no}, rows~{page_no * page_size}",
                  flush=True)
        if next_key is None:
            break
        time.sleep(0.03)
    frames = [pd.read_csv(p) for p in sorted(pages_dir.glob("page_*.csv"))]
    bars = pd.concat(frames, ignore_index=True)
    bars["time_key"] = pd.to_datetime(bars["time_key"], errors="raise")
    bars = bars.sort_values("time_key", kind="stable").reset_index(drop=True)
    if bars.empty or bars.time_key.duplicated().any() or not bars.time_key.is_monotonic_increasing:
        raise ValueError(f"duplicate, empty, or unordered capture for {code}/{timeframe}")
    for col in ("open", "high", "low", "close", "volume"):
        bars[col] = pd.to_numeric(bars[col], errors="raise")
    if not np.isfinite(bars[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)).all():
        raise ValueError(f"non-finite OHLCV values for {code}/{timeframe}")
    bad = ((bars[["open", "high", "low", "close"]] <= 0).any(axis=1)
           | (bars.volume < 0)
           | (bars.high < bars[["open", "close", "low"]].max(axis=1))
           | (bars.low > bars[["open", "close", "high"]].min(axis=1)))
    if bad.any():
        quarantine = output_dir / "quarantine" / target.name
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        bars.to_csv(quarantine, index=False)
        sample = bars.loc[bad, COLUMNS].head(10).to_dict("records")
        raise ValueError(f"invalid OHLCV values for {code}/{timeframe}; quarantine={quarantine}; bad_rows={int(bad.sum())}; sample={sample}")
    session_specs = {
        "1m": (1, (9, 31)),
        "5m": (5, (9, 35)),
        "15m": (15, (9, 45)),
    }
    if timeframe in session_specs:
        minutes, expected_first = session_specs[timeframe]
        for day, indexes in bars.groupby(bars.time_key.dt.date).groups.items():
            times = bars.loc[indexes, "time_key"].reset_index(drop=True)
            first, last = times.iloc[0], times.iloc[-1]
            if (first.hour, first.minute) != expected_first or (last.hour, last.minute) not in {(13, 0), (16, 0)}:
                raise ValueError(f"unexpected RTH {timeframe} session endpoints for {code} on {day}: {first}..{last}")
            expected = pd.date_range(first, last, freq=f"{minutes}min")
            if not times.equals(pd.Series(expected)):
                raise ValueError(f"missing/irregular RTH {timeframe} bars for {code} on {day}: {first}..{last}")
    tmp_target = target.with_suffix(target.suffix + ".tmp")
    bars.to_csv(tmp_target, index=False)
    tmp_target.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    for page in pages_dir.glob("page_*.csv"):
        page.unlink()
    return {"symbol": symbol, "timeframe": timeframe, "status": "CAPTURED",
            "rows": len(bars), "first": str(bars.time_key.iloc[0]),
            "last": str(bars.time_key.iloc[-1]), "path": str(target),
            "bytes": target.stat().st_size, "sha256": digest,
            "pages": page_no, "elapsed_seconds": round(time.perf_counter() - started, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--symbols", help="comma-separated candidate symbols; defaults to all 30")
    ap.add_argument("--timeframes", default="D1,1H,15m,5m,1m")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11111)
    ap.add_argument("--page-size", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=1, help="parallel local OpenD quote contexts (keep conservative)")
    ap.add_argument("--max-pages", type=int, help="stop after N pages per symbol/timeframe, preserving checkpoints")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    definitions = config["markets"]["us"]["symbols"]
    sectors = {item["symbol"]: item["sector"] for item in definitions}
    symbols = args.symbols.split(",") if args.symbols else list(sectors)
    missing = sorted(set(symbols) - set(sectors))
    if missing:
        raise ValueError(f"symbols are not in the frozen Round27 config: {missing}")
    timeframes = args.timeframes.split(",")
    if set(timeframes) - set(TIMEFRAMES) or not timeframes:
        raise ValueError(f"unsupported timeframes: {timeframes}")
    if args.page_size < 1:
        raise ValueError("page-size must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.workers < 1 or args.workers > 6:
        raise ValueError("workers must be between 1 and 6")

    def capture_symbol(symbol: str) -> list[dict]:
        ctx = OpenQuoteContext(host=args.host, port=args.port)
        local_results = []
        try:
            for tf in timeframes:
                try:
                    row = capture_one(ctx, f"US.{symbol}", symbol, tf, args.start, args.end,
                                      args.output_dir, args.page_size, args.max_pages, args.force)
                    row["status"] = row["status"]
                except Exception as exc:
                    row = {"symbol": symbol, "timeframe": tf, "status": "BLOCKED",
                           "error": f"{type(exc).__name__}: {exc}"}
                row["sector"] = sectors[symbol]
                local_results.append(row)
                print(json.dumps(row, sort_keys=True), flush=True)
        finally:
            ctx.close()
        return local_results

    results = []
    if args.workers == 1:
        for symbol in symbols:
            results.extend(capture_symbol(symbol))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(capture_symbol, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                results.extend(future.result())
    manifest_path = args.output_dir / "capture_manifest_latest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    combined = {(row["symbol"], row["timeframe"]): row for row in previous.get("results", [])}
    combined.update({(row["symbol"], row["timeframe"]): row for row in results})
    manifest = {"schema": "stock-razor-round27-local-opend-capture-v1",
                "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
                "start": args.start, "end": args.end,
                "adjustment": "QFQ", "session": "RTH",
                "data_source": "local Futu/OpenD; no cloud/provider fallback",
                "results": [combined[key] for key in sorted(combined)]}
    atomic_json(manifest_path, manifest)
    return 0 if all(item["status"] in {"CAPTURED", "ALREADY_PRESENT"} for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
