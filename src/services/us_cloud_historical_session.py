"""Pure reader for already obtained STOCK RAZOR US OpenD historical bars.

A closed historical market-data snapshot is research evidence only. STALE
snapshots may be studied after the market, but can NEVER grant real-time
signals, feed admission or external Paper brokerage permissions.

No API client, tokens, provider, cloud, file or broker I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time
from decimal import Decimal
from collections import defaultdict
from collections.abc import Mapping
from zoneinfo import ZoneInfo

from .closed_bar_paper_replay import Closed15mBar, UpstreamHourlyGate

NY = ZoneInfo("America/New_York")
ACCEPTED_HISTORICAL_FLAGS = frozenset(("HISTORICAL_QUERY", "STALE"))


@dataclass(frozen=True)
class USOfflineMarketSession:
    symbol: str
    exchange_local_date: str
    bars: tuple[Closed15mBar, ...]
    provider: str = "futu"
    feed: str = "opend"
    historical_only: bool = True
    source_identity_independently_verified: bool = False
    live_currentness_verified: bool = False
    full_session_checked: bool = True
    cloud_deployment_performed: bool = False
    external_broker_paper_verified: bool = False
    paper_auto_ready: bool = False
    radar_admission: str = "BLOCKED"
    live_trade: bool = False


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} not an ISO timestamp")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} invalid ISO timestamp") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError(f"{field} must carry timezone offset")
    return d.astimezone(timezone.utc)


def partition_historical_opend_us_15m(
    response: Mapping[str, object], *, symbol: str
) -> tuple[USOfflineMarketSession, ...]:
    """Split bounded historical 15m market-bar response into RTH sessions.

    Requiring exactly 26 closed 15m bars is specific to FULL US RTH days;
    partial sessions, half days and sessions spanning malformed DST data are
    blocked, not silently assigned a credible Paper replay.
    """
    if not isinstance(response, Mapping) or response.get("ok") is not True:
        raise ValueError("MARKET_HISTORY_RESPONSE_INVALID")
    if response.get("status") not in ("PASS", "STALE"):
        raise ValueError("MARKET_HISTORY_STATUS_NOT_SUPPORTED")
    if not isinstance(symbol, str) or not 1 <= len(symbol) <= 12 or not symbol.isascii() or not symbol.isalnum():
        raise ValueError("SYMBOL_INVALID")
    if not isinstance(response.get("bars"), list) or not 1 <= len(response["bars"]) <= 1300:
        raise ValueError("HISTORICAL_BAR_COUNT_INVALID")

    target = "US." + symbol.upper()
    grouped: dict[str, list[Closed15mBar]] = defaultdict(list)
    for row in response["bars"]:
        if not isinstance(row, Mapping):
            raise ValueError("BAR_ROW_INVALID")
        if (
            row.get("symbol") != target
            or row.get("market") != "us"
            or row.get("asset_type") not in ("stock", "etf")
            or row.get("timeframe") != "15m"
            or row.get("session") != "regular"
            or row.get("provider") != "futu"
            or row.get("feed") != "opend"
            or row.get("is_closed") is not True
            or row.get("is_complete") is not True
        ):
            raise ValueError("MARKET_HISTORY_PROVENANCE_UNQUALIFIED")
        flags = row.get("quality_flags")
        if (
            not isinstance(flags, list)
            or not all(isinstance(x, str) for x in flags)
            or "HISTORICAL_QUERY" not in flags
            or any(x not in ACCEPTED_HISTORICAL_FLAGS for x in flags)
        ):
            raise ValueError("HISTORICAL_QUALITY_FLAGS_UNQUALIFIED")
        start, end = _utc(row.get("bar_start_utc"), "bar_start"), _utc(row.get("bar_end_utc"), "bar_end")
        provider_end = _utc(row.get("source_timestamp_utc"), "source_timestamp")
        received_at = _utc(row.get("received_at_utc"), "received_at")
        if provider_end != end or received_at < end:
            raise ValueError("SOURCE_TIMESTAMP_NOT_CLOSED")
        obj = Closed15mBar(
            start, end,
            Decimal(str(row.get("open"))), Decimal(str(row.get("high"))),
            Decimal(str(row.get("low"))), Decimal(str(row.get("close"))),
            Decimal(str(row.get("volume"))), "futu/opend",
        )
        date = start.astimezone(NY).date().isoformat()
        grouped[date].append(obj)
    if len(grouped) > 50:
        raise ValueError("TOO_MANY_REPLAY_SESSIONS")

    sessions: list[USOfflineMarketSession] = []
    for date, bars in sorted(grouped.items()):
        ordered = sorted(bars, key=lambda x: x.start)
        if len(ordered) != 26:
            raise ValueError("RTH_FULL_SESSION_INCOMPLETE")
        if ordered[0].start.astimezone(NY).time() != time(9, 30):
            raise ValueError("RTH_START_NOT_CONFIRMED")
        if ordered[-1].end.astimezone(NY).time() != time(16, 0):
            raise ValueError("RTH_END_NOT_CONFIRMED")
        if any(b.start != ordered[0].start + timedelta(minutes=15*i) for i,b in enumerate(ordered)):
            raise ValueError("RTH_15M_GAP_OR_DUPLICATE")
        if any(b.start.astimezone(NY).date().isoformat()!=date for b in ordered):
            raise ValueError("EXCHANGE_LOCAL_DATE_CHANGED")
        sessions.append(USOfflineMarketSession(
            symbol=symbol.upper(),
            exchange_local_date=date,
            bars=tuple(ordered),
        ))
    return tuple(sessions)


def select_historical_full_60m_gate(
    response: Mapping[str, object],
    *,
    symbol: str,
    decision_as_of: datetime,
    upstream_passed: bool,
) -> UpstreamHourlyGate:
    """PIT-safe 60m source selection; ignore final 30m RTH pseudo-hour.

    Does not calculate a strategy trend or infer permission. The caller must
    provide upstream_passed as a boolean from its independent research model.
    """
    as_of = decision_as_of.astimezone(timezone.utc) if isinstance(decision_as_of, datetime) and decision_as_of.tzinfo is not None and decision_as_of.utcoffset() is not None else None
    if as_of is None or not isinstance(upstream_passed, bool):
        raise ValueError("60M_GATE_ARGUMENTS_INVALID")
    if not isinstance(response, Mapping) or response.get("ok") is not True or response.get("status") not in ("PASS", "STALE"):
        raise ValueError("HOURLY_RESPONSE_INVALID")
    if not isinstance(symbol, str) or not symbol.isascii() or not symbol.isalnum():
        raise ValueError("SYMBOL_INVALID")
    rows = response.get("bars")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValueError("HOURLY_BAR_COUNT_INVALID")
    target = "US." + symbol.upper()
    options = []
    for row in rows:
        if not isinstance(row, Mapping) or (
            row.get("symbol") != target or row.get("market") != "us"
            or row.get("timeframe") != "1h" or row.get("provider") != "futu"
            or row.get("feed") != "opend" or row.get("session") != "regular"
            or row.get("is_closed") is not True or row.get("is_complete") is not True
        ):
            raise ValueError("60M_PROVENANCE_UNQUALIFIED")
        flags = row.get("quality_flags")
        if not isinstance(flags, list) or "HISTORICAL_QUERY" not in flags or any(flag not in ACCEPTED_HISTORICAL_FLAGS for flag in flags):
            raise ValueError("HOURLY_HISTORICAL_FLAGS_UNQUALIFIED")
        start, end = _utc(row.get("bar_start_utc"), "hour_start"), _utc(row.get("bar_end_utc"), "hour_end")
        received = _utc(row.get("received_at_utc"), "hour_received")
        if _utc(row.get("source_timestamp_utc"), "hour_source_timestamp") != end or received < end:
            raise ValueError("HOURLY_TIMESTAMP_INVALID")
        if end <= start or end - start not in (timedelta(minutes=60), timedelta(minutes=30)):
            raise ValueError("HOURLY_BAR_DURATION_UNEXPECTED")
        if end <= as_of and end - start == timedelta(minutes=60):
            options.append(end)
    if len(options) != len(set(options)):
        raise ValueError("HOURLY_DUPLICATE_CLOSE")
    if not options:
        raise ValueError("NO_FULL_60M_BAR_ASOF")
    return UpstreamHourlyGate(
        closed_bar_end=max(options), passed=upstream_passed,
        bar_was_closed=True, source="futu/opend",
        bar_duration_minutes=60,
    )
