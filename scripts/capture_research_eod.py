#!/usr/bin/env python3
"""Capture small recorded EOD fixtures; never starts a provider runtime."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def capture_baostock(symbol: str, start: str, end: str):
    import baostock as bs
    code = symbol if "." in symbol else f"sh.{symbol}"
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(login.error_msg)
    try:
        query = bs.query_history_k_data_plus(code, "date,code,open,high,low,close,volume", start_date=start, end_date=end, frequency="d", adjustflag="3")
        if query.error_code != "0":
            raise RuntimeError(query.error_msg)
        rows = []
        while query.next():
            row = query.get_row_data()
            rows.append({"symbol": row[1], "date": row[0], "open": row[2], "high": row[3], "low": row[4], "close": row[5], "volume": row[6]})
        return rows
    finally:
        bs.logout()


def capture_akshare(symbol: str, start: str, end: str):
    import akshare as ak
    numeric = symbol.split(".", 1)[-1]
    frame = ak.stock_zh_a_hist(
        symbol=numeric,
        period="daily",
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        adjust="",
    )
    rows = []
    for _, row in frame.iterrows():
        rows.append({
            "symbol": symbol,
            "date": str(row["日期"]),
            "open": float(row["开盘"]),
            "high": float(row["最高"]),
            "low": float(row["最低"]),
            "close": float(row["收盘"]),
            "volume": float(row["成交量"]),
        })
    return rows


def capture_yfinance(symbol: str, start: str, end: str):
    import yfinance as yf
    frame = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)
    # Recent yfinance releases return MultiIndex columns even for one ticker.
    # Normalize them before row access so each OHLCV value is scalar.
    if getattr(frame.columns, "nlevels", 1) > 1:
        try:
            frame = frame.xs(symbol, axis=1, level=-1)
        except (KeyError, ValueError):
            frame.columns = frame.columns.get_level_values(0)

    def scalar(value):
        if hasattr(value, "iloc"):
            return value.iloc[0]
        return value

    rows = []
    for index, row in frame.iterrows():
        rows.append({"symbol": symbol, "date": index.strftime("%Y-%m-%d"), "open": float(scalar(row["Open"])), "high": float(scalar(row["High"])), "low": float(scalar(row["Low"])), "close": float(scalar(row["Close"])), "volume": float(scalar(row["Volume"]))})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=("cn", "us"), required=True)
    parser.add_argument("--source", choices=("baostock", "akshare", "yfinance"), default=None)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    source_id = args.source or ("baostock" if args.market == "cn" else "yfinance")
    if args.market == "cn" and source_id == "yfinance":
        raise ValueError("yfinance is not a CN capture source")
    if args.market == "us" and source_id != "yfinance":
        raise ValueError("only yfinance is supported for US capture")
    try:
        last_error = None
        for attempt in range(max(1, args.retries)):
            try:
                if source_id == "baostock":
                    rows = capture_baostock(args.symbol, args.start, args.end)
                elif source_id == "akshare":
                    rows = capture_akshare(args.symbol, args.start, args.end)
                else:
                    rows = capture_yfinance(args.symbol, args.start, args.end)
                break
            except Exception as exc:
                last_error = exc
                if attempt + 1 < max(1, args.retries):
                    time.sleep(2 ** attempt)
        else:
            raise last_error
    except Exception as exc:
        manifest = args.output.with_suffix(args.output.suffix + ".manifest.json")
        manifest.write_text(json.dumps({"source_id": source_id, "market": args.market, "endpoint_id": "history_eod", "retrieved_at": datetime.now(timezone.utc).isoformat(), "status": "CAPTURE_BLOCKED", "error_type": type(exc).__name__, "error": str(exc)}, indent=2), encoding="utf-8")
        print(json.dumps({"status": "CAPTURE_BLOCKED", "source_id": source_id, "market": args.market, "symbol": args.symbol, "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True))
        return 2
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("symbol", "date", "open", "high", "low", "close", "volume"))
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    manifest = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest.write_text(json.dumps({"source_id": source_id, "market": args.market, "endpoint_id": "history_eod", "retrieved_at": datetime.now(timezone.utc).isoformat(), "raw_sha256": digest, "adjustment": "unadjusted", "status": "CAPTURED_NOT_APPROVED"}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
