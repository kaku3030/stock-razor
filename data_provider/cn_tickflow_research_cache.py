"""Read-only, isolated TickFlow Premium minute observation (not canonical/trade)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import re
import tempfile
from typing import Any

CN = ZoneInfo("Asia/Shanghai")
SCHEMA = "stock_razor_cn_tickflow_research_observation_v0_1"
DEFAULT_PATH = "/run/stock-razor-cn-tickflow/latest-research-observation.json"
SYMBOLS = ("159611.SZ", "159209.SZ", "512730.SH", "159363.SZ")
# Expert capacity ceiling. The deployment default remains 20; explicit scans
# may use the full 200 only through the bounded batch path.
MAX_SCAN_SYMBOLS = 200
TIMEFRAMES = ("1m", "5m", "15m", "60m", "1d")
# Twenty symbols × five periods requires a larger bounded private envelope;
# this remains a hard reader/writer limit and is not public market-data output.
MAX_BYTES = 64_000_000
MAX_AGE_SECONDS = 180
_LABEL_END = {
    "1m": frozenset(
        f"{minute//60:02d}:{minute%60:02d}"
        for minute in (*range(9*60+31, 11*60+31),
                       *range(13*60+1, 15*60+1))
    ),
    "15m": frozenset(("09:45","10:00","10:15","10:30","10:45","11:00",
       "11:15","11:30","13:15","13:30","13:45","14:00","14:15",
       "14:30","14:45","15:00")),
    "60m": frozenset(("10:30","11:30","14:00","15:00")),
    "5m": frozenset(f"{minute//60:02d}:{minute%60:02d}"
        for minute in (*range(9*60+35,11*60+31,5),
                       *range(13*60+5,15*60+1,5))),
    # The provider 1d row is calendar-date stamped 00:00 local;
    # not an exchange bar-end timestamp and never proof of close.
    "1d": frozenset(("00:00",)),
}
_SYMBOL_RE = re.compile(r"^(?:[0-9]{6})\.(?:SH|SZ)$")
_ALLOWED_PERIODS = {"1m":240,"5m":144,"15m":96,"60m":24,"1d":60}
_HISTORY_LOOKBACK_DAYS = {"15m":14,"60m":14,"1d":120}
_HISTORY_WARMUP_ROWS = {"15m":96,"60m":24,"1d":60}
# Recover at most four omitted entries for each bounded provider route.
_MAX_BATCH_FALLBACKS_PER_PERIOD = 4
_MAX_BATCH_FALLBACKS_PER_OBSERVATION = (
    _MAX_BATCH_FALLBACKS_PER_PERIOD * 7  # 3 historical + 4 current-session periods
)
_SOURCE = "TICKFLOW_PREMIUM"


class _BatchSymbolFallbackError(RuntimeError):
    """Provider-free public failure for a missing-symbol recovery attempt."""


def resolve_scan_symbols(value: str | None = None) -> tuple[str, ...]:
    """Resolve an explicit, bounded scan list without changing the safe default."""
    if value is None or not value.strip():
        return SYMBOLS
    symbols = tuple(item.strip().upper() for item in value.replace(";", ",").split(",")
                    if item.strip())
    if (not symbols or len(symbols) > MAX_SCAN_SYMBOLS
            or len(set(symbols)) != len(symbols)
            or not all(_SYMBOL_RE.fullmatch(item) for item in symbols)):
        raise ValueError("invalid scan symbols")
    return symbols


class _BatchKlinesFacade:
    """Fetch historical warmup and current-session bars through distinct routes."""

    def __init__(self, client: Any, period_symbols: dict[str, tuple[str, ...]],
                 periods: dict[str, int], batch_size: int,
                 now_utc: datetime) -> None:
        self._frames: dict[tuple[str, str], Any] = {}
        self._intraday_frames: dict[tuple[str, str], Any] = {}
        self._fallback_count = 0
        end_ms = int(now_utc.timestamp() * 1000)

        def fetch_route(period: str, symbols: tuple[str, ...], *, intraday: bool):
            count = periods[period]
            try:
                method = (client.klines.intraday_batch if intraday
                          else client.klines.batch)
                kwargs = {
                    "period": period, "count": count, "as_dataframe": False,
                    "show_progress": False, "max_workers": 5,
                    "batch_size": batch_size,
                }
                if not intraday:
                    lookback_days = _HISTORY_LOOKBACK_DAYS[period]
                    kwargs.update({
                        "start_time": end_ms - lookback_days * 24 * 60 * 60 * 1000,
                        "end_time": end_ms,
                    })
                    if period == "1d":
                        kwargs["adjust"] = "none"
                result = method(list(symbols), **kwargs)
                if not isinstance(result, dict):
                    raise ValueError("batch SDK shape invalid")
                missing = tuple(symbol for symbol in symbols if symbol not in result)
                if (len(missing) > _MAX_BATCH_FALLBACKS_PER_PERIOD
                        or self._fallback_count + len(missing)
                        > _MAX_BATCH_FALLBACKS_PER_OBSERVATION):
                    raise ValueError("batch SDK symbol missing")
                self._fallback_count += len(missing)
                frames = dict(result)
                for symbol in missing:
                    try:
                        if intraday:
                            frame = client.klines.intraday(
                                symbol, period=period, count=count,
                                as_dataframe=False,
                            )
                        else:
                            fallback_kwargs = {
                                "period": period, "count": count,
                                "start_time": kwargs["start_time"],
                                "end_time": kwargs["end_time"],
                                "adjust": "none", "as_dataframe": False,
                            }
                            frame = client.klines.get(symbol, **fallback_kwargs)
                    except Exception:
                        failure = _BatchSymbolFallbackError(
                            "batch symbol fallback failed"
                        )
                        failure._tickflow_stage = (
                            f"BATCH_{period.upper()}_"
                            f"{'INTRADAY' if intraday else 'HISTORY'}_FALLBACK"
                        )
                        raise failure from None
                    frames[symbol] = frame
                return frames
            except Exception as exc:
                if not isinstance(exc, _BatchSymbolFallbackError):
                    exc._tickflow_stage = (
                        f"BATCH_{period.upper()}_"
                        f"{'INTRADAY' if intraday else 'HISTORY'}_FETCH"
                    )
                raise

        for period, period_symbol_list in period_symbols.items():
            if period in _HISTORY_LOOKBACK_DAYS:
                historical = fetch_route(period, period_symbol_list, intraday=False)
                for symbol, frame in historical.items():
                    self._frames[(symbol, period)] = frame
                if period in ("15m", "60m"):
                    current = fetch_route(period, period_symbol_list, intraday=True)
                    for symbol, frame in current.items():
                        self._intraday_frames[(symbol, period)] = frame
            else:
                # 1m/5m supplemental rows remain current-session diagnostics.
                current = fetch_route(period, period_symbol_list, intraday=True)
                for symbol, frame in current.items():
                    self._frames[(symbol, period)] = frame

    def get(self, symbol: str, *, period: str, count: int,
            adjust: str, as_dataframe: bool) -> Any:
        del count, adjust, as_dataframe
        return self._frames[(symbol, period)]

    def get_intraday(self, symbol: str, *, period: str) -> Any:
        return self._intraday_frames[(symbol, period)]

def _timestamp(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (in