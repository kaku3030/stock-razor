"""TickFlow A-share bar evidence: clock maturity vs provider finality.

Offline, provider-agnostic **research-only** audit of two distinct AWS cache
publications. This cannot establish vendor/exchange close because the
TickFlow K-lines compact response contains no authenticated finality field.
It never changes the production research cache or any admission gate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import isfinite
import re
from typing import Any, Mapping

from data_provider.cn_tickflow_research_cache import CN, SCHEMA, SYMBOLS, _LABEL_END

_PERIODS = frozenset(("5m", "15m", "60m"))
_SOURCE = "TICKFLOW_PREMIUM"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SOURCE_AGE_LIMIT = 180.0
_MIN_POLL_GAP_SECONDS = 10.0
_MAX_POLL_GAP_SECONDS = 300.0
_GRACE_SECONDS = 90.0


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _row(snapshot: Mapping, symbol: str, timeframe: str, label: str) -> dict | None:
    try:
        frame = snapshot["symbols"][symbol][timeframe]
        rows = frame["rows"]
        if not isinstance(rows, list) or len(rows) > 144:
            return None
        matches = [
            row for row in rows
            if isinstance(row, dict) and row.get("label") == label
        ]
        if len(matches) != 1:
            return None
        row = matches[0]
        if (
            row.get("bar_finality") != "NOT_VERIFIED"
            or row.get("is_partial_bar") is not True
            or row.get("ohlc_validation") != "STRICT"
        ):
            return None
        for field in ("open", "high", "low", "close", "volume"):
            val = row.get(field)
            if type(val) not in (int, float) or not isfinite(val):
                return None
            if field == "volume" and val < 0:
                return None
            if field != "volume" and val <= 0:
                return None
        if row["high"] < max(row["open"], row["close"], row["low"]):
            return None
        if row["low"] > min(row["open"], row["close"], row["high"]):
            return None
        amount = row.get("amount")
        if amount is not None and (
            type(amount) not in (int, float) or not isfinite(amount)
            or amount < 0
        ):
            return None
        return row
    except (KeyError, TypeError):
        return None


def _digest(row: Mapping) -> str:
    # Only the digest leaves the private audit; never OHLC, amount or volume.
    fields = ("open", "high", "low", "close", "volume", "amount")
    payload = json.dumps(
        [row.get(field) for field in fields],
        separators=(",", ":"), allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()[:16]


def _result(status: str, *, same: bool = False, fingerprint: str | None = None) -> dict:
    return {
        "status": status,
        "two_poll_stable_research_only": same,
        "bar_clock_matured": status in (
            "STABLE_AFTER_MATURITY_NOT_VENDOR_FINAL",
            "ROW_MUTATED_AFTER_MATURITY",
        ),
        "bar_finality": "NOT_VERIFIED",
        "exchange_bar_finality": "NOT_VERIFIED",
        "provider_finality_attestation": "NOT_AVAILABLE_IN_KLINES_SCHEMA",
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "canonical_write_authorized": False,
        "live_trade": False,
        "provider_requests": 0,
        "fingerprint": fingerprint if same else None,
    }


def audit_tickflow_bar_stability(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    symbol: str,
    timeframe: str,
    label: str,
    now_utc: datetime,
) -> dict:
    """Classify two cached publications; never infer official close from time.

    Both snapshots must be valid independent TickFlow research observations,
    from the same source runtime revision, with strictly advancing sequences,
    poll clocks, and a regular-session bar-end boundary older than 90s.
    """
    if (
        symbol not in SYMBOLS or timeframe not in _PERIODS
        or not isinstance(label, str)
        or type(now_utc) is not datetime or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
        or not isinstance(first, Mapping)
        or not isinstance(second, Mapping)
    ):
        return _result("INVALID_INPUT")
    try:
        boundary = datetime.strptime(label, "%Y-%m-%d %H:%M").replace(tzinfo=CN)
    except (ValueError, TypeError):
        return _result("INVALID_LABEL")
    if boundary.strftime("%H:%M") not in _LABEL_END[timeframe]:
        return _result("INVALID_LABEL")
    now = now_utc.astimezone(timezone.utc)
    if boundary.astimezone(timezone.utc) > now - timedelta(seconds=_GRACE_SECONDS):
        return _result("BOUNDARY_NOT_MATURE")
    prev_time = _time(first.get("observed_at_utc"))
    next_time = _time(second.get("observed_at_utc"))
    if prev_time is None or next_time is None:
        return _result("SOURCE_PROVENANCE_INVALID")
    # The *first* observation must also be after the provider boundary
    # grace. Two identical in-flight candles before the close prove nothing.
    if prev_time < boundary.astimezone(timezone.utc) + timedelta(
        seconds=_GRACE_SECONDS,
    ):
        return _result("FIRST_POLL_BEFORE_MATURITY")
    age = (now - next_time).total_seconds()
    gap = (next_time - prev_time).total_seconds()
    if (
        gap < _MIN_POLL_GAP_SECONDS or gap > _MAX_POLL_GAP_SECONDS
        or not 0 <= age <= _SOURCE_AGE_LIMIT
        or next_time > now
    ):
        return _result("POLL_LINEAGE_INVALID")
    revisions = (first.get("repo_sha"), second.get("repo_sha"))
    if (
        not all(isinstance(s, str) and _SHA.fullmatch(s) for s in revisions)
        or revisions[0] != revisions[1]
        or any(s.get("schema") != SCHEMA or s.get("provider") != _SOURCE
               or s.get("status") != "PASS_RESEARCH_ONLY"
               or s.get("research_only") is not True
               or s.get("radar_admission") != "BLOCKED"
               or s.get("source_arbiter_admission") != "BLOCKED"
               or s.get("live_trade") is not False
               or s.get("canonical_write_authorized") is not False
               for s in (first, second))
    ):
        return _result("SOURCE_PROVENANCE_INVALID")
    a, b = first.get("sequence"), second.get("sequence")
    if type(a) is not int or type(b) is not int or b <= a:
        return _result("SEQUENCE_NOT_ADVANCING")
    old_row = _row(first, symbol, timeframe, label)
    new_row = _row(second, symbol, timeframe, label)
    if old_row is None or new_row is None:
        return _result("BAR_NOT_OBSERVED_OR_UNSAFE")
    d0, d1 = _digest(old_row), _digest(new_row)
    if d0 != d1:
        return _result("ROW_MUTATED_AFTER_MATURITY")
    # Stabilized prices are NOT exchange-final, even after 2 independent polls.
    return _result(
        "STABLE_AFTER_MATURITY_NOT_VENDOR_FINAL",
        same=True, fingerprint=d1,
    )
