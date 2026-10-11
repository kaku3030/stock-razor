"""Offline A-share same-provider 15m-to-daily OHLCV consistency audit.

Not a claim of provider independence, timestamp currentness, auction coverage,
correct price, or permission to trade. Daily extrema may include auction
prints outside provider 15m session bars. This file performs NO I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping, Sequence
import re

CN_15M_END_LABELS = (
    "09:45", "10:00", "10:15", "10:30",
    "10:45", "11:00", "11:15", "11:30",
    "13:15", "13:30", "13:45", "14:00",
    "14:15", "14:30", "14:45", "15:00",
)
DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)


@dataclass(frozen=True)
class CnCrossframeAudit:
    status: str
    reasons: tuple[str, ...]
    date: str
    source: str
    intraday_count: int
    high_gap: Decimal | None = None
    low_gap: Decimal | None = None
    volume_gap: Decimal | None = None
    independent_source_verified: bool = False
    intraday_currentness_verified: bool = False
    auction_coverage_verified: bool = False
    signal_confirmation_allowed: bool = False
    broker_io_performed: bool = False
    live_trade: bool = False


def _price(row: Mapping[str, object], field: str) -> Decimal:
    value = row.get(field)
    if isinstance(value, bool) or value is None:
        raise ValueError("OHLCV numeric field invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise ValueError("OHLCV numeric field invalid") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("OHLCV price field invalid")
    return result


def _volume(row: Mapping[str, object]) -> Decimal:
    value = row.get("volume_raw")
    if isinstance(value, bool) or value is None:
        raise ValueError("volume field invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise ValueError("volume field invalid") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("volume field invalid")
    return result


def audit_cn_15m_against_daily(
    daily: Mapping[str, object],
    intraday: Sequence[Mapping[str, object]],
    *,
    price_tolerance: Decimal = Decimal("0"),
    volume_tolerance: Decimal = Decimal("1"),
) -> CnCrossframeAudit:
    """Compare all 16 exchange-session BAR_END labels to one daily candle.

    Every result is offline diagnostic evidence, not a live-data permission.
    """
    if not isinstance(daily, Mapping) or not isinstance(intraday, (tuple, list)):
        raise ValueError("one daily mapping and a sequence of 15m mappings are required")
    date = daily.get("label")
    if not isinstance(date, str) or not DAY_PATTERN.fullmatch(date):
        raise ValueError("daily date label must be YYYY-MM-DD")
    if not isinstance(price_tolerance, Decimal) or not price_tolerance.is_finite() or price_tolerance < 0:
        raise ValueError("price tolerance invalid")
    if not isinstance(volume_tolerance, Decimal) or not volume_tolerance.is_finite() or volume_tolerance < 0:
        raise ValueError("volume tolerance invalid")
    provider = daily.get("provider")
    if not isinstance(provider, str) or provider not in ("tencent", "eastmoney"):
        raise ValueError("provider unsupported")
    if daily.get("volume_unit") != "HAND":
        raise ValueError("daily volume unit must be HAND")
    reasons: set[str] = set()
    if len(intraday) != 16:
        reasons.add("INCOMPLETE_15M_SESSION")
    if any(not isinstance(bar, Mapping) for bar in intraday):
        raise ValueError("intraday row must be mapping")
    expected = tuple(f"{date} {label}" for label in CN_15M_END_LABELS)
    observed = tuple(bar.get("label") for bar in intraday)
    if observed != expected:
        reasons.add("15M_SESSION_TIMELINE_UNQUALIFIED")
    if any(bar.get("provider") != provider for bar in intraday):
        reasons.add("CROSS_PROVIDER_LINEAGE_UNKNOWN")
    if any(bar.get("volume_unit") != "HAND" for bar in intraday):
        reasons.add("VOLUME_UNIT_MISMATCH")

    daily_o, daily_h, daily_l, daily_c = (
        _price(daily, key) for key in ("open", "high", "low", "close")
    )
    daily_v = _volume(daily)
    if daily_l > min(daily_o, daily_c) or daily_h < max(daily_o, daily_c) or daily_l > daily_h:
        raise ValueError("daily OHLC internally inconsistent")
    if not intraday:
        return CnCrossframeAudit("INCOMPLETE", tuple(sorted(reasons)), date, provider, 0)
    candles = []
    for bar in intraday:
        o, h, l, c = (_price(bar, key) for key in ("open", "high", "low", "close"))
        v = _volume(bar)
        if l > min(o, c) or h < max(o, c) or l > h:
            raise ValueError("15m OHLC internally inconsistent")
        candles.append((o, h, l, c, v))
    intraday_h = max(x[1] for x in candles)
    intraday_l = min(x[2] for x in candles)
    intraday_v = sum((x[4] for x in candles), Decimal("0"))
    high_gap = daily_h - intraday_h
    low_gap = daily_l - intraday_l
    volume_gap = daily_v - intraday_v
    if abs(daily_o - candles[0][0]) > price_tolerance:
        reasons.add("SESSION_OPEN_DIVERGENCE")
    if abs(daily_c - candles[-1][3]) > price_tolerance:
        reasons.add("SESSION_CLOSE_DIVERGENCE")
    if abs(high_gap) > price_tolerance:
        reasons.add("DAILY_HIGH_NOT_RECONCILED")
    if abs(low_gap) > price_tolerance:
        reasons.add("DAILY_LOW_NOT_RECONCILED")
    if abs(volume_gap) > volume_tolerance:
        reasons.add("SESSION_VOLUME_DIVERGENCE")
    return CnCrossframeAudit(
        status="MATCHED_OFFLINE_ONLY" if not reasons else "DIVERGENT_OR_INCOMPLETE",
        reasons=tuple(sorted(reasons)),
        date=date, source=provider, intraday_count=len(candles),
        high_gap=high_gap, low_gap=low_gap, volume_gap=volume_gap,
    )
