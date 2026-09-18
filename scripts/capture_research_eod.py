#!/usr/bin/env python3
"""Capture small recorded EOD fixtures; never starts a provider runtime."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
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


def _resolve_column(frame, *aliases: str) -> str:
    """Resolve provider-specific OHLCV column names without assuming one schema."""
    available = {str(column).strip().lower(): column for column in frame.columns}
    for alias in aliases:
        column = available.get(alias.strip().lower())
        if column is not None:
            return column
    raise KeyError(aliases[0])


def capture_akshare(symbol: str, start: str, end: str):
    import akshare as ak
    numeric = symbol.split(".", 1)[-1]
    try:
        frame = ak.stock_zh_a_hist(
            symbol=numeric, period="daily", start_date=start.replace("-", ""),
            end_date=end.replace("-", ""), adjust="",
        )
        columns = {"date": "日期", "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量"}
    except Exception:
        # Eastmoney-backed endpoint can intermittently close the connection;
        # use AKShare's Tencent-backed historical endpoint as a source-local
        # fallback, while preserving the same recorded-capture semantics.
        frame = ak.stock_zh_a_hist_tx(
            symbol=numeric, start_date=start.replace("-", ""),
            end_date=end.replace("-", ""), adjust="",
        )
        columns = {"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "vol"}
    resolved = {
        "date": _resolve_column(frame, columns["date"], "date", "日期", "时间"),
        "open": _resolve_column(frame, columns["open"], "open", "开盘"),
        "high": _resolve_column(frame, columns["high"], "high", "最高"),
        "low": _resolve_column(frame, columns["low"], "low", "最低"),
        "close": _resolve_column(frame, columns["close"], "close", "收盘"),
        "volume": _resolve_column(frame, columns["volume"], "volume", "vol", "成交量", "成交额"),
    }
    rows = []
    for _, row in frame.iterrows():
        rows.append({
            "symbol": symbol,
            "date": str(row[resolved["date"]]),
            "open": float(row[resolved["open"]]),
            "high": float(row[resolved["high"]]),
            "low": float(row[resolved["low"]]),
            "close": float(row[resolved["close"]]),
            "volume": float(row[resolved["volume"]]),
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

    def finite_float(value, field: str, date: str) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"non-finite {field} for {symbol} at {date}") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"non-finite {field} for {symbol} at {date}")
        return numeric

    rows = []
    for index, row in frame.iterrows():
        date = index.strftime("%Y-%m-%d")
        rows.append({
            "symbol": symbol,
            "date": date,
            "open": finite_float(scalar(row["Open"]), "open", date),
            "high": finite_float(scalar(row["High"]), "high", date),
            "low": finite_float(scalar(row["Low"]), "low", date),
            "close": finite_float(scalar(row["Close"]), "close", date),
            "volume": finite_float(scalar(row["Volume"]), "volume", date),
        })
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
        # Never leave a prior/staged CSV that could look valid beside a blocked manifest.
        args.output.unlink(missing_ok=True)
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

