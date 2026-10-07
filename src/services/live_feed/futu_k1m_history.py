from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
import math
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from data_provider.market_data_adapter import Bar, evaluate_health


FUTU_US_KLINE_TIMEZONE = ZoneInfo("America/New_York")
FUTU_US_K1M_FUTURE_SKEW_SECONDS = 5
FUTU_US_REGULAR_FIRST_END = time(9, 31)
FUTU_US_REGULAR_LAST_END = time(16, 0)


@dataclass(frozen=True)
class FutuK1MHistoricalTail:
    symbol: str
    time_key: str


@dataclass(frozen=True)
class FutuK1MHistoricalNormalization:
    """Research-only historical K1M facts bounded by next-label closure proof."""

    bars: tuple[Bar, ...]
    unresolved_tail: FutuK1MHistoricalTail | None
    rows_seen: int
    closure_method: str = field(default="NEXT_TIME_KEY_PROGRESS", init=False)
    research_only: bool = field(default=True, init=False)
    can_promote: bool = field(default=False, init=False)
    radar_admission: str = field(default="BLOCKED", init=False)
    live_trade: bool = field(default=False, init=False)


@dataclass(frozen=True)
class _ParsedHistoricalRow:
    symbol: str
    time_key: str
    interval_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float | None


def normalize_futu_k1m_history_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    received_at: datetime,
    expected_symbol: str | None = None,
) -> FutuK1MHistoricalNormalization:
    """Normalize same-OpenD historical K1M rows without inventing closure.

    Futu US K1M time_key is a qualified interval-END label. Historical query
    availability does not itself prove that the newest row is closed, so only
    a row followed by a strictly later provider label is emitted as a closed
    canonical fact. The final row remains an unresolved tail regardless of
    wall-clock age.

    This boundary is provider-SDK free and cannot promote currentness,
    delivery mode, Radar admission, or execution.
    """

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")

    normalized_expected = (
        str(expected_symbol).strip().upper() if expected_symbol is not None else None
    )
    if normalized_expected is not None and not normalized_expected.startswith("US."):
        raise ValueError("expected_symbol must use canonical US.* form")

    parsed = tuple(_parse_row(row, expected_symbol=normalized_expected) for row in rows)
    if not parsed:
        return FutuK1MHistoricalNormalization(
            bars=(),
            unresolved_tail=None,
            rows_seen=0,
        )

    symbols = {row.symbol for row in parsed}
    if len(symbols) != 1:
        raise ValueError("historical K1M normalization accepts exactly one symbol per call")

    for prior, current in zip(parsed, parsed[1:]):
        if current.interval_end <= prior.interval_end:
            raise ValueError("historical K1M time_key must be strictly increasing")

    bars = tuple(
        _to_historical_bar(row, received_at=received_at)
        for row in parsed[:-1]
    )
    tail = FutuK1MHistoricalTail(
        symbol=parsed[-1].symbol,
        time_key=parsed[-1].time_key,
    )
    return FutuK1MHistoricalNormalization(
        bars=bars,
        unresolved_tail=tail,
        rows_seen=len(parsed),
    )


def _parse_row(
    row: Mapping[str, object],
    *,
    expected_symbol: str | None,
) -> _ParsedHistoricalRow:
    symbol = str(row.get("code") or "").strip().upper()
    if not symbol.startswith("US."):
        raise ValueError("historical K1M row requires canonical US.* code")
    if expected_symbol is not None and symbol != expected_symbol:
        raise ValueError("historical K1M row symbol does not match expected_symbol")

    raw_time = str(row.get("time_key") or "").strip()
    if not raw_time:
        raise ValueError("historical K1M row requires time_key")
    try:
        local_end_naive = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("historical K1M time_key has invalid format") from exc
    if not FUTU_US_REGULAR_FIRST_END <= local_end_naive.time() <= FUTU_US_REGULAR_LAST_END:
        raise ValueError("historical K1M row is outside the qualified regular session")

    interval_end = local_end_naive.replace(
        tzinfo=FUTU_US_KLINE_TIMEZONE
    ).astimezone(timezone.utc)

    return _ParsedHistoricalRow(
        symbol=symbol,
        time_key=raw_time,
        interval_end=interval_end,
        open=_finite_number(row, "open"),
        high=_finite_number(row, "high"),
        low=_finite_number(row, "low"),
        close=_finite_number(row, "close"),
        volume=_finite_number(row, "volume"),
        turnover=_optional_finite_number(row, "turnover"),
    )


def _to_historical_bar(
    row: _ParsedHistoricalRow,
    *,
    received_at: datetime,
) -> Bar:
    flags = ["HISTORICAL_QUERY"]
    observed = received_at.astimezone(timezone.utc)
    if (row.interval_end - observed).total_seconds() > FUTU_US_K1M_FUTURE_SKEW_SECONDS:
        flags.append("TIMESTAMP_MISMATCH")

    prices = (row.open, row.high, row.low, row.close)
    if any(value <= 0 for value in prices):
        flags.append("NON_POSITIVE_PRICE")
    if not (
        row.low <= row.open <= row.high
        and row.low <= row.close <= row.high
    ):
        flags.append("INVALID_OHLC")
    if row.volume < 0:
        flags.append("NEGATIVE_VOLUME")

    # Historical facts are intentionally not currentness evidence. Timestamp
    # semantics are proven, while continuity/cross-check remain conservative
    # until their independent evidence layers qualify them.
    health = evaluate_health(
        freshness=0,
        completeness=1,
        timestamp=1,
        provider=1,
        continuity=0.5,
        cross_check=0.5,
        quality_flags=flags,
    )
    age_ms = max(0, round((observed - row.interval_end).total_seconds() * 1000))

    return Bar(
        symbol=row.symbol,
        market="us",
        asset_type="stock",
        timeframe="1m",
        bar_start=row.interval_end - timedelta(minutes=1),
        bar_end=row.interval_end,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        amount=row.turnover,
        provider="futu",
        source_timestamp=row.interval_end,
        received_at=observed,
        session="regular",
        is_closed=True,
        is_complete=True,
        feed="opend",
        latency_ms=age_ms,
        freshness_ms=age_ms,
        health=health,
        quality_flags=health.quality_flags,
    )


def _finite_number(row: Mapping[str, object], field_name: str) -> float:
    if field_name not in row or row.get(field_name) is None:
        raise ValueError(f"historical K1M row requires {field_name}")
    try:
        value = float(row[field_name])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"historical K1M {field_name} must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"historical K1M {field_name} must be finite")
    return value


def _optional_finite_number(
    row: Mapping[str, object],
    field_name: str,
) -> float | None:
    value = row.get(field_name)
    if value is None:
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"historical K1M {field_name} must be numeric") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"historical K1M {field_name} must be finite")
    return normalized
