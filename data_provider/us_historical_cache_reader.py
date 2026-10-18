"""Bounded, provider-free reads from the persisted US historical-bar cache."""

from __future__ import annotations

from datetime import date, datetime, time
import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo


DEFAULT_CACHE_PATH = "/run/stock-razor-us-livefeed/historical-bars.json"
SUPPORTED_TIMEFRAMES = ("D1", "1h", "15m", "5m", "1m")
MAX_LIMIT = 1000
MAX_INTRADAY_DAYS = 31
MAX_DAILY_DAYS = 366
SOURCE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ET = ZoneInfo("America/New_York")


def _blocked(status: str, error: str, **extra) -> dict:
    return {"ok": False, "status": status, "error": error, "radar_admission": "BLOCKED", "live_trade": False, **extra}


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or ("+" not in value and "-" not in value[10:] and not value.endswith("Z")):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _normalize_bar(row: object, *, session_dates: set[date], timeframe: str) -> dict | None:
    if not isinstance(row, dict):
        return None
    session_date = _parse_date(row.get("session_date"))
    timestamp = _parse_timestamp(row.get("timestamp"))
    if session_date is None or timestamp is None or session_date not in session_dates:
        return None
    local_timestamp = timestamp.astimezone(ET)
    if local_timestamp.date() != session_date:
        return None
    if timeframe != "D1" and not (time(9, 30) < local_timestamp.timetz().replace(tzinfo=None) <= time(16, 0)):
        return None
    if row.get("session") != "RTH" or row.get("closed") is not True:
        return None
    values = [row.get(field) for field in ("open", "high", "low", "close", "volume")]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in values):
        return None
    open_price, high, low, close, volume = values
    if min(open_price, high, low, close) <= 0 or volume < 0 or high < max(open_price, close) or low > min(open_price, close):
        return None
    normalized = dict(row)
    normalized["timestamp"] = timestamp.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
    return normalized


def _validate_rows(rows: object, *, session_dates: set[date], timeframe: str) -> list[dict] | None:
    if not isinstance(rows, list):
        return None
    normalized = [_normalize_bar(row, session_dates=session_dates, timeframe=timeframe) for row in rows]
    if any(row is None for row in normalized):
        return None
    result = [row for row in normalized if row is not None]
    timestamps = [row["timestamp"] for row in result]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        return None
    return result


def _encode_cursor(snapshot_sha256: str, query_sha256: str, offset: int) -> str:
    payload = {"version": 1, "snapshot_sha256": snapshot_sha256, "query_sha256": query_sha256, "offset": offset}
    return base64.urlsafe_b64encode(_canonical_json(payload)).decode("ascii").rstrip("=")


def _decode_cursor(value: object) -> dict | None:
    if not isinstance(value, str) or not value or len(value) > 512:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, TypeError, binascii.Error):
        return None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "snapshot_sha256", "query_sha256", "offset"}
        or payload.get("version") != 1
        or not isinstance(payload.get("snapshot_sha256"), str)
        or not SOURCE_SHA256_RE.fullmatch(payload["snapshot_sha256"])
        or not isinstance(payload.get("query_sha256"), str)
        or not SOURCE_SHA256_RE.fullmatch(payload["query_sha256"])
        or type(payload.get("offset")) is not int
        or payload["offset"] < 0
    ):
        return None
    return payload


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
    cursor: str | None = None,
    path: str | None = None,
) -> dict:
    """Read a bounded page from a pre-existing, integrity-checked cache."""
    normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not normalized or not normalized.replace(".", "").isalnum() or len(normalized) > 16:
        return _blocked("INVALID_ARGUMENT", "INVALID_SYMBOL")
    start = _parse_date(start_date)
    end = _parse_date(end_date)
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
    cache = Path(path) if path else _cache_path()
    if not cache.exists():
        return _blocked("CACHE_MISSING", "HISTORICAL_CACHE_MISSING", cache_path=str(cache), provider_requests=0)
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return _blocked("CACHE_INVALID", "HISTORICAL_CACHE_INVALID", cache_path=str(cache), provider_requests=0)
    if not isinstance(payload, dict) or payload.get("schema") != "stock_razor_us_historical_cache_v1":
        return _blocked("CACHE_INVALID", "HISTORICAL_CACHE_SCHEMA_INVALID", cache_path=str(cache), provider_requests=0)
    metadata = payload.get("source_metadata")
    source_hash = payload.get("source_sha256")
    calendar = payload.get("calendar")
    if (
        not isinstance(payload.get("cache_version"), str)
        or not isinstance(payload.get("source"), str)
        or not isinstance(metadata, dict)
        or not isinstance(source_hash, str)
        or not SOURCE_SHA256_RE.fullmatch(source_hash)
        or _sha256(metadata) != source_hash
        or not isinstance(calendar, dict)
        or calendar.get("timezone") != "America/New_York"
        or calendar.get("rth_start") != "09:30"
        or calendar.get("rth_end") != "16:00"
        or not isinstance(calendar.get("trading_dates"), list)
    ):
        return _blocked("CACHE_INVALID", "HISTORICAL_CACHE_METADATA_INVALID", cache_path=str(cache), provider_requests=0)
    session_dates = {_parse_date(value) for value in calendar["trading_dates"]}
    if None in session_dates:
        return _blocked("CACHE_INVALID", "HISTORICAL_CACHE_CALENDAR_INVALID", cache_path=str(cache), provider_requests=0)
    session_dates.discard(None)
    symbols = payload.get("symbols")
    rows = symbols.get(normalized, {}).get(timeframe) if isinstance(symbols, dict) and isinstance(symbols.get(normalized), dict) else None
    if not isinstance(rows, list):
        return _blocked("NO_DATA", "HISTORICAL_CACHE_SYMBOL_OR_TIMEFRAME_MISSING", symbol=normalized, timeframe=timeframe, provider_requests=0)
    validated_rows = _validate_rows(rows, session_dates=session_dates, timeframe=timeframe)
    if validated_rows is None:
        return _blocked("CACHE_INVALID", "HISTORICAL_CACHE_BAR_INVALID", symbol=normalized, timeframe=timeframe, provider_requests=0)
    snapshot_sha256 = _sha256(payload)
    query_sha256 = _sha256({
        "symbol": normalized, "start_date": start.isoformat(), "end_date": end.isoformat(),
        "timeframe": timeframe, "adjustment": adjustment, "session": session, "limit": limit,
    })
    selected = [row for row in validated_rows if start <= _parse_date(row["session_date"]) <= end]
    offset = 0
    if cursor is not None:
        decoded_cursor = _decode_cursor(cursor)
        if decoded_cursor is None:
            return _blocked("INVALID_ARGUMENT", "INVALID_CURSOR")
        if decoded_cursor["snapshot_sha256"] != snapshot_sha256:
            return _blocked("CACHE_INVALID", "HISTORICAL_CACHE_SNAPSHOT_CHANGED", provider_requests=0)
        if decoded_cursor["query_sha256"] != query_sha256:
            return _blocked("INVALID_ARGUMENT", "HISTORICAL_CURSOR_QUERY_MISMATCH")
        offset = decoded_cursor["offset"]
        if offset > len(selected):
            return _blocked("INVALID_ARGUMENT", "INVALID_CURSOR")
    page = selected[offset : offset + limit]
    next_cursor = _encode_cursor(snapshot_sha256, query_sha256, offset + len(page)) if offset + len(page) < len(selected) else None
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
        "cache_version": payload["cache_version"],
        "cache_snapshot_sha256": snapshot_sha256,
        "source": payload["source"],
        "source_sha256": source_hash,
        "provider_finality": "UNKNOWN",
        "historical_only": True,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "provider_requests": 0,
    }
