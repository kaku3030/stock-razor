from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isclose
from typing import Mapping
from zoneinfo import ZoneInfo

from data_provider.market_data_adapter import Bar


@dataclass(frozen=True)
class FutuK5MCrossCheckResult:
    status: str
    mismatches: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    purpose: str = "CROSS_CHECK_ONLY"
    radar_admission: str = "BLOCKED"
    live_trade: bool = False

    @property
    def can_promote(self) -> bool:
        return False


def _number(row: Mapping[str, object], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_number(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-8)


def compare_canonical_5m_to_futu_native(
    canonical: Bar,
    native: Mapping[str, object],
    *,
    native_timezone_name: str = "America/New_York",
    timezone_semantics_verified: bool = False,
    native_is_forming: bool | None = None,
) -> FutuK5MCrossCheckResult:
    """Fail-closed canonical 1m-derived 5m vs native OpenD K_5M check.

    Raw OpenD time_key is an interval-end label and is compared with the
    canonical bar end rendered in the caller-declared provider timezone.
    Unless timestamp semantics were independently verified, an otherwise
    exact match remains UNKNOWN.
    """

    mismatches: list[str] = []
    unknowns: list[str] = []

    if canonical.market != "us" or canonical.timeframe != "5m":
        raise ValueError("canonical input must be a US 5m Bar")
    if canonical.bar_end - canonical.bar_start != timedelta(minutes=5):
        mismatches.append("BUCKET_BOUNDARY_MISMATCH")
    if not canonical.is_complete:
        unknowns.append("CANONICAL_INCOMPLETE")
    if not canonical.is_closed:
        unknowns.append("CANONICAL_FORMING")

    symbol = str(native.get("code") or "").strip()
    if symbol != canonical.symbol:
        mismatches.append("SYMBOL_MISMATCH")

    raw_time_key = str(native.get("time_key") or "").strip()
    try:
        native_local = datetime.strptime(raw_time_key, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        native_local = None
        mismatches.append("TIME_KEY_PARSE_MISMATCH")

    if native_local is not None:
        expected_local = (
            canonical.bar_end.astimezone(ZoneInfo(native_timezone_name))
            .replace(tzinfo=None)
        )
        if native_local != expected_local:
            mismatches.append("TIME_KEY_MISMATCH")

    comparisons = (
        ("OPEN_MISMATCH", canonical.open, _number(native, "open")),
        ("HIGH_MISMATCH", canonical.high, _number(native, "high")),
        ("LOW_MISMATCH", canonical.low, _number(native, "low")),
        ("CLOSE_MISMATCH", canonical.close, _number(native, "close")),
        ("VOLUME_MISMATCH", canonical.volume, _number(native, "volume")),
        ("TURNOVER_MISMATCH", canonical.amount, _number(native, "turnover")),
    )
    for flag, canonical_value, native_value in comparisons:
        if not _same_number(canonical_value, native_value):
            mismatches.append(flag)

    if native_is_forming is None:
        unknowns.append("NATIVE_FORMING_SEMANTICS_UNKNOWN")
    elif canonical.is_closed == native_is_forming:
        mismatches.append("FORMING_SEMANTICS_MISMATCH")

    if not timezone_semantics_verified:
        unknowns.append("TIMESTAMP_SEMANTICS_UNVERIFIED")

    mismatches = list(dict.fromkeys(mismatches))
    unknowns = list(dict.fromkeys(unknowns))
    status = "FAIL" if mismatches else ("UNKNOWN" if unknowns else "PASS")
    return FutuK5MCrossCheckResult(
        status=status,
        mismatches=tuple(mismatches),
        unknowns=tuple(unknowns),
    )
