"""Fail-closed, provider-I/O-free US daily *historical research* cache read.

This is NOT an intraday D1 closure endpoint: Futu's native K_DAY cache
explicitly excludes the current New York calendar date.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from data_provider.us_canonical_runtime_reader import read_us_livefeed_health
from src.services.live_feed.futu_us_daily_history import SCHEMA

DEFAULT_DAILY_PATH = "/run/stock-razor-us-livefeed/daily-history.json"
US_EASTERN = ZoneInfo("America/New_York")
SYMBOL = re.compile(r"US\.[A-Z][A-Z0-9.-]{0,31}\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")


def _blocked(reason: str) -> dict:
    return {
        "ok": False, "status": "BLOCKED", "reason": reason,
        "timeframe": "1d", "bars": [], "bar_count": 0,
        "research_only": True, "historical_query": True,
        "current_session_daily_bar": "NOT_AVAILABLE",
        "provider_finality": "NOT_VERIFIED",
        "can_confirm_signal": False, "provider_requests": 0,
        "source_arbiter_admission": "BLOCKED", "radar_admission": "BLOCKED",
        "paper_auto_ready": False, "live_trade": False,
    }


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("not finite")
    return number


def read_us_completed_daily_research(
    symbol: str,
    *,
    limit: int = 5,
    path: str | None = None,
    now_utc: datetime | None = None,
    max_age_seconds: int = 172800,
    livefeed_health: dict | None = None,
) -> dict:
    """Read existing OpenD K_DAY history without querying OpenD or accounts.

    Requires same runtime/commit as an independently fresh US livefeed
    heartbeat. Historical prior-session observations never become current
    daily, provider closure, a trade signal or an admission claim.
    """
    normalized = str(symbol or "").strip().upper()
    # Never reinterpret another exchange prefix as a US ticker.
    if normalized.startswith(("HK.", "CN.", "SH.", "SZ.", "BJ.")):
        return _blocked("INVALID_SYMBOL")
    if not normalized.startswith("US."):
        normalized = "US." + normalized
    if not SYMBOL.fullmatch(normalized):
        return _blocked("INVALID_SYMBOL")
    if type(limit) is not int or not 1 <= limit <= 120:
        return _blocked("INVALID_LIMIT")
    if type(max_age_seconds) is not int or not 60 <= max_age_seconds <= 172800:
        return _blocked("INVALID_MAX_AGE")
    now = now_utc or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return _blocked("INVALID_CLOCK")
    now = now.astimezone(timezone.utc)

    health = livefeed_health if livefeed_health is not None else read_us_livefeed_health(now_utc=now)
    if not isinstance(health, dict) or not (
        health.get("ok") is True
        and health.get("status") == "HEALTHY"
        # Intraday canonical snapshot age and current-session delivery
        # are independent of a prior-session K_DAY historical file. A
        # healthy heartbeat may coexist with a STALE intraday snapshot
        # off-session; never turn that snapshot staleness into a false
        # historical D1 outage. INVALID/UNAVAILABLE still fail closed.
        and health.get("canonical_snapshot_status") in ("PASS", "STALE")
        and health.get("delivery_mode") in ("REALTIME", "UNKNOWN")
        and health.get("radar_admission") == "BLOCKED"
        and health.get("live_trade") is False
    ):
        return _blocked("LIVEFEED_HEALTH_UNVERIFIED")
    repo_sha = health.get("repo_sha")
    incarnation = health.get("runtime_instance_id")
    if not isinstance(repo_sha, str) or not SHA.fullmatch(repo_sha) or not isinstance(incarnation, str) or not incarnation:
        return _blocked("LIVEFEED_LINEAGE_UNVERIFIED")

    source_path = path or os.environ.get("STOCK_RAZOR_US_DAILY_HISTORY_PATH", DEFAULT_DAILY_PATH)
    try:
        # 3 MB bound prevents loading an unexpectedly large or corrupted cache.
        if Path(source_path).stat().st_size > 3_000_000:
            return _blocked("DAILY_CACHE_TOO_LARGE")
        with open(source_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return _blocked("DAILY_CACHE_UNAVAILABLE")

    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return _blocked("DAILY_SCHEMA_MISMATCH")
    if payload.get("repo_sha") != repo_sha or payload.get("runtime_instance_id") != incarnation:
        return _blocked("DAILY_LIVEFEED_LINEAGE_MISMATCH")
    if not (
        payload.get("status") == "PASS"
        and payload.get("provider") == "futu"
        and payload.get("feed") == "opend"
        and payload.get("same_opend_context_required") is True
        and payload.get("research_only") is True
        and payload.get("historical_query") is True
        and payload.get("currentness_proven") is False
        and payload.get("bar_closure_promotion_authorized") is False
        and payload.get("can_confirm_signal") is False
        and payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
    ):
        return _blocked("DAILY_SAFETY_CONTRACT_VIOLATION")
    try:
        stamped = datetime.fromisoformat(payload["emitted_at_utc"])
        if stamped.tzinfo is None or stamped.utcoffset() is None:
            return _blocked("DAILY_TIMESTAMP_UNVERIFIED")
        age = (now - stamped.astimezone(timezone.utc)).total_seconds()
        if not 0 <= age <= max_age_seconds:
            return _blocked("DAILY_SOURCE_STALE")
    except (KeyError, ValueError, TypeError, OverflowError):
        return _blocked("DAILY_TIMESTAMP_UNVERIFIED")

    symbols = payload.get("symbols")
    item = symbols.get(normalized) if isinstance(symbols, dict) else None
    if not isinstance(item, dict) or not (
        item.get("status") == "PASS"
        and item.get("symbol") == normalized
        and item.get("completed_prior_session_only") is True
        and item.get("historical_query") is True
        and item.get("currentness_proven") is False
        and item.get("bar_closure_promotion_authorized") is False
        and item.get("radar_admission") == "BLOCKED"
        and item.get("live_trade") is False
    ):
        return _blocked("DAILY_SYMBOL_NOT_QUALIFIED")
    source_rows = item.get("rows")
    if not isinstance(source_rows, list) or not source_rows or len(source_rows) > 260:
        return _blocked("DAILY_ROWS_UNAVAILABLE")

    latest_allowed = min(now.astimezone(US_EASTERN).date(), stamped.astimezone(US_EASTERN).date())
    prior = None
    bars = []
    for row in source_rows:
        if not isinstance(row, dict):
            return _blocked("DAILY_ROW_INVALID")
        date_str = row.get("date")
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date()
            if day.isoformat() != date_str or day >= latest_allowed or (prior and day <= prior):
                return _blocked("DAILY_DATE_NOT_PRIOR_OR_ORDERED")
            prior = day
            o, h, l, c = (_number(row.get(key)) for key in ("open", "high", "low", "close"))
            volume = _number(row.get("volume"))
            amount = None if row.get("amount") is None else _number(row["amount"])
        except (TypeError, ValueError, OverflowError):
            return _blocked("DAILY_ROW_INVALID")
        if (
            min(o, h, l, c) <= 0 or h < max(o, l, c)
            or l > min(o, h, c) or volume < 0
            or (amount is not None and amount < 0)
            or row.get("provider") != "futu" or row.get("feed") != "opend"
            or row.get("quality_flags") != ["HISTORICAL_QUERY"]
        ):
            return _blocked("DAILY_OHLCV_OR_ORIGIN_INVALID")
        bars.append({"date": date_str, "symbol": normalized, "timeframe": "1d",
                     "open": o, "high": h, "low": l, "close": c, "volume": volume,
                     "amount": amount, "provider": "futu", "feed": "opend",
                     "quality_flags": ["HISTORICAL_QUERY"]})

    if len(bars) < limit:
        return _blocked("INSUFFICIENT_HISTORICAL_DAILY_ROWS")
    return {
        **_blocked(""), "ok": True, "status": "PASS_HISTORICAL_ONLY",
        "reason": None, "symbol": normalized, "bars": bars[-limit:],
        "bar_count": limit, "total_bar_count": len(bars),
        "repo_sha": repo_sha, "runtime_instance_id": incarnation,
        "source_observed_at_utc": payload["emitted_at_utc"],
        "source_age_seconds": age, "same_opend_context": True,
    }
