"""Independent TickFlow K-line publication stability witness (research ONLY).

A pair of private AWS poll snapshots can prove repeated identical OHLCVA
observations and the appearance of the *next* scheduled label. Neither is a
provider/exchange finality acknowledgment. This module has no provider I/O.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
import re
from typing import Any, Mapping

from .cn_tickflow_research_cache import CN, SCHEMA, _LABEL_END, SYMBOLS

_PERIODS = ("5m", "15m", "60m")
_FIELDS = ("open", "high", "low", "close", "volume", "amount")
_LABEL = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_READY = "STABLE_AFTER_NEXT_LABEL_RESEARCH_ONLY"
_SAFETY = {
    "research_only": True, "radar_admission": "BLOCKED",
    "source_arbiter_admission": "BLOCKED", "live_trade": False,
    "can_confirm_signal": False, "canonical_write_authorized": False,
}


def _result(reason: str, *, poll_gap_seconds: float | None = None) -> dict:
    return {
        "schema": "stock_razor_tickflow_close_witness_research_v0_1",
        "status": _READY if reason == "STABLE_TWO_POLLS" else "BLOCKED",
        "reason": reason,
        "poll_gap_seconds": poll_gap_seconds,
        "bar_label_stability": (
            "REPEATED_OHLCVA_RESEARCH_ONLY" if reason == "STABLE_TWO_POLLS"
            else "NOT_VERIFIED"
        ),
        "provider_bar_finality": "NOT_VERIFIED",
        "exchange_bar_finality": "NOT_VERIFIED",
        "trading_session_calendar": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "paper_auto_ready": False,
        "live_trade": False,
        "provider_requests": 0,
    }


def _time(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text)
    except (OverflowError, TypeError, ValueError):
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def _safe_bar(snapshot: Mapping, symbol: str, timeframe: str, label: str):
    try:
        frame = snapshot["symbols"][symbol][timeframe]
        items = frame["rows"]
        if (not isinstance(items, list)
                or frame.get("closure") != "NOT_VERIFIED"
                or frame.get("currentness") != "UNPROVEN"):
            return None
        hits = [row for row in items if isinstance(row, dict)
                and row.get("label") == label]
        if len(hits) != 1:
            return None
        item = hits[0]
        if (item.get("bar_finality") != "NOT_VERIFIED"
                or item.get("is_partial_bar") is not True
                or item.get("ohlc_validation") not in (
                    "STRICT", "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
                )):
            return None
        fields = []
        for name in _FIELDS:
            value = item.get(name)
            if value is None and name == "amount" and (
                    item.get("amount_availability") == "SDK_OMITTED"):
                fields.append(None)
            elif (type(value) not in (int, float) or not isfinite(value)
                    or value < 0):
                return None
            else:
                fields.append(float(value))
        if any(value is not None and value <= 0 for value in fields[:4]):
            return None
        opening, high, low, closing = fields[:4]
        if high < max(opening, closing, low) or low > min(
                opening, closing, high):
            # Never treat a malformed OHLC record as a stable, closed bar.
            return None
        return (
            *fields, item.get("amount_availability"),
            item.get("ohlc_validation"),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _next_label(bar: datetime, timeframe: str) -> str | None:
    labels = sorted(_LABEL_END[timeframe])
    current = bar.strftime("%H:%M")
    if current not in labels:
        return None
    later = [v for v in labels if v > current]
    return (bar.strftime("%Y-%m-%d ") + later[0]) if later else None


def audit_repeated_tickflow_bar(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    symbol: str,
    timeframe: str,
    bar_end_label: str,
    now_utc: datetime,
    min_poll_gap_seconds: int = 15,
    close_grace_seconds: int = 90,
) -> dict:
    """Witness bounded post-boundary *stability*, NEVER certified finality.

    Input: two already-collected private TickFlow snapshots from independent
    collector polls. Output: fixed enums/counts only; no OHLC or credentials.
    """
    if (symbol not in SYMBOLS or timeframe not in _PERIODS
            or not isinstance(bar_end_label, str)
            or _LABEL.fullmatch(bar_end_label) is None
            or not isinstance(now_utc, datetime)
            or now_utc.tzinfo is None or now_utc.utcoffset() is None
            or type(min_poll_gap_seconds) is not int
            or not 15 <= min_poll_gap_seconds <= 120
            or type(close_grace_seconds) is not int
            or not 90 <= close_grace_seconds <= 300
            or not isinstance(first, Mapping)
            or not isinstance(second, Mapping)):
        return _result("INVALID_INPUT")
    try:
        bar_end = datetime.strptime(
            bar_end_label, "%Y-%m-%d %H:%M"
        ).replace(tzinfo=CN)
    except ValueError:
        return _result("INVALID_LABEL")
    next_label = _next_label(bar_end, timeframe)
    if next_label is None:
        return _result("NEXT_GRID_LABEL_UNAVAILABLE")
    next_end = datetime.strptime(
        next_label, "%Y-%m-%d %H:%M"
    ).replace(tzinfo=CN)
    now = now_utc.astimezone(timezone.utc)
    if next_end.astimezone(timezone.utc) > now - timedelta(
            seconds=close_grace_seconds):
        return _result("NEXT_GRID_NOT_MATURED")

    identities = []
    for snapshot in (first, second):
        if (snapshot.get("schema") != SCHEMA
                or snapshot.get("provider") != "TICKFLOW_PREMIUM"
                or snapshot.get("status") != "PASS_RESEARCH_ONLY"
                or any(type(snapshot.get(k)) is not type(v)
                       or snapshot.get(k) != v for k, v in _SAFETY.items())):
            return _result("UNTRUSTED_RESEARCH_SNAPSHOT")
        sha = snapshot.get("repo_sha")
        if not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
            return _result("INVALID_SOURCE_SHA")
        seq = snapshot.get("sequence")
        stamped = _time(snapshot.get("observed_at_utc"))
        if type(seq) is not int or seq < 1 or stamped is None:
            return _result("INVALID_POLL_IDENTITY")
        identities.append((sha, seq, stamped))
    sha1, seq1, at1 = identities[0]
    sha2, seq2, at2 = identities[1]
    gap = (at2 - at1).total_seconds()
    if sha1 != sha2:
        return _result("SOURCE_SHA_CHANGED")
    if seq2 <= seq1 or not min_poll_gap_seconds <= gap <= 180:
        return _result("INDEPENDENT_POLL_NOT_PROVEN")
    if not 0 <= (now - at2).total_seconds() <= 180:
        return _result("LATEST_SOURCE_STALE_OR_FUTURE")
    if at1 < bar_end.astimezone(timezone.utc) or (
            at2 < next_end.astimezone(timezone.utc)):
        return _result("POLL_PRECEDES_BAR_GRID")

    baseline = _safe_bar(first, symbol, timeframe, bar_end_label)
    latest = _safe_bar(second, symbol, timeframe, bar_end_label)
    next_bar = _safe_bar(second, symbol, timeframe, next_label)
    if baseline is None or latest is None or next_bar is None:
        return _result("CLOSED_GRID_DATA_INCOMPLETE")
    if baseline != latest:
        return _result("BAR_REVISED_BETWEEN_POLLS")
    return _result("STABLE_TWO_POLLS", poll_gap_seconds=round(gap, 2))


def attach_research_stability_witness(
    current: dict[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    now_utc: datetime,
) -> None:
    """Attach bounded no-quote witnesses within the existing worker poll.

    No extra SDK calls, retained disk files or provider finality promotion.
    Only a same-day prior bar with a following label can be considered.
    """
    if not isinstance(current, dict) or not isinstance(now_utc, datetime):
        raise ValueError("invalid private witness inputs")
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("invalid private witness clock")
    today = now_utc.astimezone(CN).strftime("%Y-%m-%d")
    symbols = current.get("symbols", {})
    if not isinstance(symbols, dict):
        raise ValueError("invalid private witness frames")
    for symbol in SYMBOLS:
        frames = symbols.get(symbol, {})
        if not isinstance(frames, dict):
            continue
        for timeframe in _PERIODS:
            frame = frames.get(timeframe)
            if not isinstance(frame, dict):
                continue
            rows = frame.get("rows", [])
            if not isinstance(rows, list) or len(rows) < 2:
                continue
            candidate = rows[-2].get("label") if isinstance(rows[-2], dict) else None
            if not isinstance(candidate, str) or not candidate.startswith(today + " "):
                continue
            witness = (
                audit_repeated_tickflow_bar(
                    previous, current, symbol=symbol,
                    timeframe=timeframe, bar_end_label=candidate,
                    now_utc=now_utc,
                )
                if previous is not None else _result("NO_PRIOR_POLL")
            )
            # The reader revalidates these exact research-only fields. The
            # label is a public scheduled candle-end time, not raw OHLC.
            frame["bar_stability_witness"] = {
                "bar_end_label": candidate,
                **witness,
            }
