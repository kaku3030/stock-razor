"""Fail-closed US daily research history sourced from the same Futu OpenD.

Daily history is a context input only. It cannot prove realtime currentness,
bar closure, Radar admission, or execution readiness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo


US_EASTERN = ZoneInfo("America/New_York")
SCHEMA = "stock_razor_futu_us_daily_history_v1"


def _symbol(value: object) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol.startswith("US.") or not symbol[3:]:
        raise ValueError("expected canonical US.* symbol")
    return symbol


def _number(value: object, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def _provider_date(value: object):
    raw = str(value or "").strip()
    if len(raw) < 10:
        raise ValueError("time_key is missing a provider date")
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("time_key provider date is invalid") from exc


def normalize_futu_us_daily_history_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    expected_symbol: str,
    observed_at_utc: datetime,
    required_rows: int = 120,
) -> dict:
    """Normalize completed prior-session K_DAY rows for research context.

    The current New York calendar date is always excluded. This avoids
    manufacturing daily-bar closure from wall-clock assumptions during an
    active or premarket session.
    """

    if observed_at_utc.tzinfo is None or observed_at_utc.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    if required_rows < 60:
        raise ValueError("required_rows must be at least 60")

    symbol = _symbol(expected_symbol)
    cutoff_date = observed_at_utc.astimezone(US_EASTERN).date()
    normalized: list[dict] = []
    seen_dates = set()

    for raw in rows:
        if not isinstance(raw, Mapping):
            return _blocked(symbol, cutoff_date, required_rows, "INVALID_ROW_SHAPE")
        raw_symbol = str(raw.get("code") or symbol).strip().upper()
        if raw_symbol != symbol:
            return _blocked(symbol, cutoff_date, required_rows, "SYMBOL_MISMATCH")
        try:
            day = _provider_date(raw.get("time_key"))
        except ValueError:
            return _blocked(symbol, cutoff_date, required_rows, "DATE_PARSE_ERROR")
        if day >= cutoff_date:
            continue
        if day in seen_dates:
            return _blocked(symbol, cutoff_date, required_rows, "DUPLICATE_DAILY_DATE")
        seen_dates.add(day)

        try:
            open_ = _number(raw.get("open"), field="open")
            high = _number(raw.get("high"), field="high")
            low = _number(raw.get("low"), field="low")
            close = _number(raw.get("close"), field="close")
            volume = _number(raw.get("volume"), field="volume")
            turnover_raw = raw.get("turnover")
            amount = None if turnover_raw in (None, "") else _number(turnover_raw, field="turnover")
        except ValueError:
            return _blocked(symbol, cutoff_date, required_rows, "INVALID_NUMERIC_FIELD")

        if min(open_, high, low, close) <= 0:
            return _blocked(symbol, cutoff_date, required_rows, "NON_POSITIVE_PRICE")
        if high < max(open_, close, low) or low > min(open_, close, high):
            return _blocked(symbol, cutoff_date, required_rows, "INVALID_OHLC")
        if volume < 0 or (amount is not None and amount < 0):
            return _blocked(symbol, cutoff_date, required_rows, "NEGATIVE_VOLUME_OR_AMOUNT")

        normalized.append(
            {
                "date": day.isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
                "provider": "futu",
                "feed": "opend",
                "quality_flags": ["HISTORICAL_QUERY"],
            }
        )

    dates = [item["date"] for item in normalized]
    if dates != sorted(dates):
        return _blocked(symbol, cutoff_date, required_rows, "DAILY_DATES_NOT_STRICTLY_ORDERED")

    if len(normalized) < required_rows:
        return _blocked(
            symbol,
            cutoff_date,
            required_rows,
            "INSUFFICIENT_COMPLETED_DAILY_ROWS",
            observed_count=len(normalized),
        )

    selected = normalized[-required_rows:]
    return {
        "status": "PASS",
        "symbol": symbol,
        "row_count": len(selected),
        "latest_date": selected[-1]["date"],
        "rows": selected,
        "required_rows": required_rows,
        "cutoff_market_date": cutoff_date.isoformat(),
        "completed_prior_session_only": True,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "reasons": [],
    }


def _blocked(
    symbol,
    cutoff_date,
    required_rows,
    reason,
    *,
    observed_count: int = 0,
) -> dict:
    return {
        "status": "BLOCKED",
        "symbol": symbol,
        "row_count": 0,
        "observed_count": observed_count,
        "latest_date": None,
        "rows": [],
        "required_rows": required_rows,
        "cutoff_market_date": cutoff_date.isoformat(),
        "completed_prior_session_only": True,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "reasons": [reason],
    }


DailyFetcher = Callable[[str, str, str], Sequence[Mapping[str, object]]]


def build_futu_us_daily_history(
    symbols: Sequence[str],
    *,
    fetch_rows: DailyFetcher,
    repo_sha: str,
    runtime_instance_id: str,
    observed_at_utc: datetime,
    required_rows: int = 120,
    lookback_calendar_days: int = 260,
) -> dict:
    """Fetch and normalize daily research history for all configured US symbols."""

    sha = str(repo_sha or "").strip().lower()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("repo_sha must be an exact 40-character git SHA")
    if not str(runtime_instance_id or "").strip():
        raise ValueError("runtime_instance_id is required")
    if lookback_calendar_days < 180:
        raise ValueError("lookback_calendar_days must be at least 180")
    if observed_at_utc.tzinfo is None or observed_at_utc.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")

    normalized_symbols = tuple(dict.fromkeys(_symbol(symbol) for symbol in symbols))
    market_date = observed_at_utc.astimezone(US_EASTERN).date()
    start_date = market_date - timedelta(days=lookback_calendar_days)
    results = {}

    for symbol in normalized_symbols:
        try:
            rows = fetch_rows(symbol, start_date.isoformat(), market_date.isoformat())
            result = normalize_futu_us_daily_history_rows(
                rows,
                expected_symbol=symbol,
                observed_at_utc=observed_at_utc,
                required_rows=required_rows,
            )
        except Exception as exc:
            result = _blocked(
                symbol,
                market_date,
                required_rows,
                f"DAILY_QUERY_EXCEPTION:{type(exc).__name__}",
            )
        results[symbol] = result

    passed = sum(item["status"] == "PASS" for item in results.values())
    overall = "PASS" if passed == len(results) else ("PARTIAL" if passed else "BLOCKED")
    return {
        "schema": SCHEMA,
        "repo_sha": sha,
        "runtime_instance_id": str(runtime_instance_id).strip(),
        "emitted_at_utc": observed_at_utc.astimezone(timezone.utc).isoformat(),
        "status": overall,
        "symbols": results,
        "required_rows": required_rows,
        "lookback_calendar_days": lookback_calendar_days,
        "provider": "futu",
        "feed": "opend",
        "same_opend_context_required": True,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def write_futu_us_daily_history(path: str | os.PathLike[str], payload: Mapping) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
