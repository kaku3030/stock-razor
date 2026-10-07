"""Fail-closed server-side bridge from canonical US bars to the VTI.

The browser never receives provider credentials or the internal snapshot-read
bearer token. This service performs no provider I/O. It reads the already
exported canonical snapshot and optionally persists only closure-proven bars
into the downstream settled-bar cache.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Callable

from data_provider.local_bar_cache import SettledBarCache
from data_provider.us_canonical_runtime_reader import read_us_market_bars


SUPPORTED_VTI_TIMEFRAMES = ("1m", "5m", "15m", "1h")
DEFAULT_CACHE_PATH = "data/cache/settled-bars.sqlite3"


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _aware_iso(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("before must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("before must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("before must be timezone-aware")
    return parsed.isoformat()


def _dedupe_sort(bars: list[dict]) -> list[dict]:
    by_end: dict[str, dict] = {}
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        end = bar.get("bar_end_utc")
        if not isinstance(end, str) or not end:
            continue
        by_end[end] = bar
    return [by_end[key] for key in sorted(by_end)]


def _settled_only(bars: list[dict]) -> list[dict]:
    return [
        bar
        for bar in bars
        if isinstance(bar, dict)
        and bar.get("is_closed") is True
        and bar.get("is_complete") is True
    ]


class VtiMarketDataService:
    """Read canonical bars and use a local cache as a non-authoritative accelerator."""

    def __init__(
        self,
        *,
        cache_enabled: bool | None = None,
        cache_path: str | Path | None = None,
        us_reader: Callable[..., dict] = read_us_market_bars,
    ) -> None:
        self.cache_enabled = (
            _truthy(os.environ.get("STOCK_RAZOR_SETTLED_BAR_CACHE_ENABLED"))
            if cache_enabled is None
            else bool(cache_enabled)
        )
        self.cache_path = Path(
            cache_path
            or os.environ.get("STOCK_RAZOR_SETTLED_BAR_CACHE_PATH")
            or DEFAULT_CACHE_PATH
        )
        self._us_reader = us_reader

    def _cache(self) -> SettledBarCache | None:
        if not self.cache_enabled:
            return None
        return SettledBarCache(self.cache_path)

    @staticmethod
    def _validate_timeframe(timeframe: object) -> str:
        frame = str(timeframe or "").strip().lower()
        if frame not in SUPPORTED_VTI_TIMEFRAMES:
            raise ValueError(
                "unsupported timeframe; expected one of "
                + ", ".join(SUPPORTED_VTI_TIMEFRAMES)
            )
        return frame

    @staticmethod
    def _validate_limit(limit: object) -> int:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 480
        ):
            raise ValueError("limit must be between 1 and 480")
        return limit

    def _read_cache_page(
        self,
        cache: SettledBarCache,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
        before: str | None,
    ) -> tuple[list[dict], bool]:
        # Read one extra row so has_more_before is evidence-backed rather than
        # inferred from a full page.
        rows = cache.read_bars(
            market="us",
            symbol=symbol,
            timeframe=timeframe,
            limit=limit + 1,
            before_bar_end_utc=before,
        )
        has_more = len(rows) > limit
        if has_more:
            rows = rows[-limit:]
        return rows, has_more

    def read_us_bars(
        self,
        symbol: object,
        *,
        timeframe: str = "15m",
        limit: int = 240,
        before: str | None = None,
    ) -> dict:
        frame = self._validate_timeframe(timeframe)
        page_limit = self._validate_limit(limit)
        before_iso = _aware_iso(before) if before is not None else None

        cache_status = "DISABLED"
        cache_error = None
        cache_write = None
        cache = None
        if self.cache_enabled:
            try:
                cache = self._cache()
                cache_status = "READY"
            except Exception as exc:  # noqa: BLE001 - cache may degrade, canonical read must remain usable.
                cache_status = "DEGRADED"
                cache_error = type(exc).__name__

        # Historical left-pagination is cache-only. This path intentionally
        # performs no provider/canonical runtime read and therefore cannot
        # create upstream request pressure.
        if before_iso is not None:
            if cache is None:
                return {
                    "ok": False,
                    "status": "NO_DATA",
                    "market": "us",
                    "symbol": str(symbol or "").strip().upper(),
                    "timeframe": frame,
                    "bars": [],
                    "bar_count": 0,
                    "has_more_before": False,
                    "has_more_after": False,
                    "source": "settled_cache",
                    "source_status": "UNAVAILABLE",
                    "cache_status": cache_status,
                    "cache_error": cache_error,
                    "research_only": True,
                    "canonical_authority": False,
                    "live_trade": False,
                }
            rows, has_more = self._read_cache_page(
                cache,
                symbol=str(symbol or "").strip().upper()
                if str(symbol or "").strip().upper().startswith("US.")
                else "US." + str(symbol or "").strip().upper(),
                timeframe=frame,
                limit=page_limit,
                before=before_iso,
            )
            return {
                "ok": bool(rows),
                "status": "PASS" if rows else "NO_DATA",
                "market": "us",
                "symbol": rows[-1]["symbol"] if rows else str(symbol or "").strip().upper(),
                "timeframe": frame,
                "bars": rows,
                "bar_count": len(rows),
                "has_more_before": has_more,
                "has_more_after": False,
                "source": "settled_cache",
                "source_status": "PASS" if rows else "NO_DATA",
                "cache_status": cache_status,
                "cache_error": cache_error,
                "research_only": True,
                "canonical_authority": False,
                "live_trade": False,
            }

        canonical = self._us_reader(symbol, timeframe=frame, limit=page_limit)
        canonical_bars = _settled_only(
            canonical.get("bars") if isinstance(canonical.get("bars"), list) else []
        )
        normalized_symbol = canonical.get("symbol")
        if not isinstance(normalized_symbol, str) or not normalized_symbol:
            raw = str(symbol or "").strip().upper()
            normalized_symbol = raw if raw.startswith("US.") else "US." + raw

        if cache is not None and canonical_bars:
            try:
                cache_write = cache.upsert_bars(canonical_bars)
            except Exception as exc:  # noqa: BLE001
                cache_status = "DEGRADED"
                cache_error = type(exc).__name__

        cached_bars: list[dict] = []
        has_more_before = False
        if cache is not None:
            try:
                cached_bars, _ = self._read_cache_page(
                    cache,
                    symbol=normalized_symbol,
                    timeframe=frame,
                    limit=page_limit,
                    before=None,
                )
            except Exception as exc:  # noqa: BLE001
                cache_status = "DEGRADED"
                cache_error = type(exc).__name__
                cached_bars = []

        combined = _dedupe_sort([*cached_bars, *canonical_bars])
        if len(combined) > page_limit:
            combined = combined[-page_limit:]

        if cache is not None and combined:
            try:
                older = cache.read_bars(
                    market="us",
                    symbol=normalized_symbol,
                    timeframe=frame,
                    limit=1,
                    before_bar_end_utc=combined[0]["bar_end_utc"],
                )
                has_more_before = bool(older)
            except Exception as exc:  # noqa: BLE001
                cache_status = "DEGRADED"
                cache_error = type(exc).__name__

        canonical_status = str(canonical.get("status") or "UNAVAILABLE")
        source = "canonical+settled_cache" if cached_bars else "canonical"
        if not canonical_bars and cached_bars:
            source = "settled_cache"
            status = "CACHE_ONLY"
        else:
            status = canonical_status if combined else "NO_DATA"

        return {
            "ok": bool(combined),
            "status": status,
            "market": "us",
            "symbol": normalized_symbol,
            "timeframe": frame,
            "bars": combined,
            "bar_count": len(combined),
            "has_more_before": has_more_before,
            "has_more_after": False,
            "source": source,
            "source_status": canonical_status,
            "source_age_seconds": canonical.get("source_age_seconds"),
            "repo_sha": canonical.get("repo_sha"),
            "runtime_instance_id": canonical.get("runtime_instance_id"),
            "sequence": canonical.get("sequence"),
            "emitted_at_utc": canonical.get("emitted_at_utc"),
            "delivery_mode": canonical.get("delivery_mode"),
            "bar_closure": canonical.get("bar_closure"),
            "cache_status": cache_status,
            "cache_error": cache_error,
            "cache_write": cache_write,
            "research_only": True,
            "canonical_authority": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }
