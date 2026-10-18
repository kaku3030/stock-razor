"""Bounded, provider-free reads from the persisted US historical-bar cache."""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path


DEFAULT_CACHE_PATH = "/run/stock-razor-us-livefeed/historical-bars.json"
SUPPORTED_TIMEFRAMES = ("D1", "1h", "15m", "5m", "1m")
MAX_LIMIT = 1000
MAX_INTRADAY_DAYS = 31
MAX_DAILY_DAYS = 366


def _blocked(status: str, error: str, **extra) -> dict:
    return {
        "ok": False,
        "status": status,
        "error": error,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        **extra,
    }


def _parse_date(value: object, field: str) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _row_date(row: object) -> date | None:
    if not isinstance(row, dict):
        return None
    value = row.get("session_date") or row.get("date") or row.get("timestamp") or row.get("time_key")
    if not isinstance(value, str):
        return None
    return _parse_date(value[:10], "bar_date")


def _cache_path() -> Path:
    return Path(os.environ.get("STOCK_RAZOR_US_HISTORICAL_CACHE_PATH", DEFAULT_CACHE_PATH))


def read_us_historical_bars(
    symbol: object,
    *,
    start_date: object,
    end_date: object,
    timeframe: str = "1h",
    adjustment: str = "qfq",
    session: str = "RTH",
    limit: int = 100,
    cursor: int | None = None,
    path: str | None = None,
) -> dict:
    """Read a bounded page from a pre-existing cache; never contacts a provider."""
    normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not normalized or not normalized.replace(".", "").isalnum() or len(normalized) > 16:
        return _blocked("INVALID_ARGUMENT", "INVALID_SYMBOL")
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start is None or end is None or start > end:
        return _blocked("INVALID_ARGUMENT", "INVALID_DATE_RANGE")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        return _blocked("INVALID_ARGUMENT", "UNSUPPORTED_TIMEFRAME", supported_timeframes=list(SUPPORTED_TIMEFRAMES))
    if adjustment != "qfq":
        return _blocked("INVALID_ARGUMENT", "UNSUPPORTED_ADJUSTMENT")
    if session != "RTH":
        return _blocked("INVALID_ARGUMENT", "UNSUPPORTED_SESSION")
    max_days = MAX_DAILY_DAYS if timeframe == "D1" else MAX_INTRADAY_DAYS
    if (end - start).days + 1 > max_days:
        return _blocked("INVALID_ARGUMENT", "DATE_RANGE_TOO_WIDE", max_days=max_days)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        return _blocked("INVALID_ARGUMENT", "INVALID_LIMIT", limit_max=MAX_LIMIT)
    if cursor is not None and (type(cursor) is not int or not 0 <= cursor <= MAX_LIMIT * 10000):
        return _blocked("INVALID_ARGUMENT", "INVALID_CURSOR")
    cache = Path(path) if path else _cache_path()
    if not cache.exists():
        return _blocked("CACHE_MISSING", "HISTORICAL_CACHE_MISSING", cache_path=str(cache), provider_requests=0)
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return _blocked("CACHE_INVALID", "HISTORICAL_CACHE_INVALID", cache_path=str(cache), provider_requests=0)
    if not isinstance(payload, dict) or payload.get("schema") != "stock_razor_us_historical_cache_v1":
        return _blocked("CACHE_INVALID", "HISTORICAL_CACHE_SCHEMA_INVALID", cache_path=str(cache), provider_requests=0)
    symbols = payload.get("symbols")
    rows = symbols.get(normalized, {}).get(timeframe) if isinstance(symbols, dict) and isinstance(symbols.get(normalized), dict) else None
    if not isinstance(rows, list):
        return _blocked("NO_DATA", "HISTORICAL_CACHE_SYMBOL_OR_TIMEFRAME_MISSING", symbol=normalized, timeframe=timeframe, provider_requests=0)
    selected = [row for row in rows if isinstance(row, dict) and (_row_date(row) is not None and start <= _row_date(row) <= end)]
    selected.sort(key=lambda row: str(row.get("timestamp") or row.get("time_key") or row.get("date") or ""))
    offset = cursor or 0
    page = selected[offset : offset + limit]
    next_cursor = offset + len(page) if offset + len(page) < len(selected) else None
    if not page:
        return _blocked("NO_DATA", "HISTORICAL_CACHE_RANGE_EMPTY", symbol=normalized, timeframe=timeframe, bars=[], next_cursor=None, provider_requests=0)
    return {
        "ok": True,
        "status": "PASS_HISTORICAL_ONLY",
        "symbol": normalized,
        "timeframe": timeframe,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "adjustment": adjustment,
        "session": session,
        "bars": page,
        "bar_count": len(page),
        "total_bar_count": len(selected),
        "next_cursor": next_cursor,
        "source": payload.get("source", "UNKNOWN"),
        "source_sha256": payload.get("source_sha256", "UNKNOWN"),
        "provider_finality": "UNKNOWN",
        "historical_only": True,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "provider_requests": 0,
    }
