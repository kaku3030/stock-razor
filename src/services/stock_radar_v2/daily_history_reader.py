"""Read and validate Futu US daily research history for isolated Radar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import pandas as pd

from src.services.live_feed.futu_us_daily_history import SCHEMA


def load_futu_us_daily_history_frames(
    path: str | Path,
    *,
    expected_repo_sha: str,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Return validated daily DataFrames plus fail-closed diagnostics."""

    expected = str(expected_repo_sha or "").strip().lower()
    if len(expected) != 40 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("expected_repo_sha must be an exact 40-character git SHA")

    try:
        with Path(path).open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return {}, _blocked(f"SOURCE_INVALID:{type(exc).__name__}")

    if not isinstance(payload, Mapping):
        return {}, _blocked("SOURCE_INVALID:ROOT")
    if payload.get("schema") != SCHEMA:
        return {}, _blocked("SOURCE_INVALID:SCHEMA")
    if payload.get("repo_sha") != expected:
        return {}, _blocked("SOURCE_REPO_SHA_MISMATCH")
    if not (
        payload.get("research_only") is True
        and payload.get("can_confirm_signal") is False
        and payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
        and payload.get("historical_query") is True
        and payload.get("currentness_proven") is False
        and payload.get("bar_closure_promotion_authorized") is False
    ):
        return {}, _blocked("SAFETY_CONTRACT_VIOLATION")
    if payload.get("status") != "PASS":
        return {}, _blocked("SOURCE_STATUS_NOT_PASS")

    symbols = payload.get("symbols")
    if not isinstance(symbols, Mapping) or not symbols:
        return {}, _blocked("SYMBOLS_MISSING")

    frames: dict[str, pd.DataFrame] = {}
    summary = {}
    for raw_symbol, item in symbols.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol.startswith("US.") or not isinstance(item, Mapping):
            return {}, _blocked("SYMBOL_CONTRACT_INVALID")
        if not (
            item.get("status") == "PASS"
            and item.get("historical_query") is True
            and item.get("currentness_proven") is False
            and item.get("radar_admission") == "BLOCKED"
            and item.get("live_trade") is False
        ):
            return {}, _blocked(f"SYMBOL_NOT_PASS:{symbol}")
        rows = item.get("rows")
        if not isinstance(rows, list) or len(rows) < 60:
            return {}, _blocked(f"INSUFFICIENT_DAILY_ROWS:{symbol}")
        normalized = []
        last_date = None
        for raw in rows:
            if not isinstance(raw, Mapping):
                return {}, _blocked(f"INVALID_DAILY_ROW:{symbol}")
            try:
                day = pd.Timestamp(str(raw["date"]))
                open_ = float(raw["open"])
                high = float(raw["high"])
                low = float(raw["low"])
                close = float(raw["close"])
                volume = float(raw["volume"])
            except Exception:
                return {}, _blocked(f"INVALID_DAILY_ROW:{symbol}")
            if day.tzinfo is not None:
                day = day.tz_convert(None)
            if last_date is not None and day <= last_date:
                return {}, _blocked(f"DAILY_DATES_NOT_STRICTLY_ORDERED:{symbol}")
            last_date = day
            if min(open_, high, low, close) <= 0:
                return {}, _blocked(f"NON_POSITIVE_PRICE:{symbol}")
            if high < max(open_, close, low) or low > min(open_, close, high):
                return {}, _blocked(f"INVALID_OHLC:{symbol}")
            if volume < 0:
                return {}, _blocked(f"NEGATIVE_VOLUME:{symbol}")
            normalized.append(
                {
                    "date": day,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            )
        frames[symbol] = pd.DataFrame(normalized)
        summary[symbol] = {
            "row_count": len(normalized),
            "latest_date": normalized[-1]["date"].date().isoformat(),
        }

    return frames, {
        "status": "PASS",
        "source_repo_sha": expected,
        "symbols": summary,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def _blocked(reason: str) -> dict:
    return {
        "status": "BLOCKED",
        "reason": reason,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


class ValidatedDailyHistoryFileCache:
    """Reuse *validated* daily research frames only for an unchanged file.

    Historical data can remain stable across thousands of Radar polls. Atomic
    replacement, in-place rewrites, missing files, source SHA changes and
    validation failures all invalidate the cache. This class never upgrades
    a historical-data safety permission or infers currentness from file age.

    Returned pandas frames must be treated as read-only by consumers.
    """

    def __init__(self) -> None:
        self._cache_key: tuple | None = None
        self._cache_value: tuple[dict[str, pd.DataFrame], dict] | None = None

    @staticmethod
    def _signature(path: str | Path) -> tuple:
        source = Path(path)
        stat = source.stat()
        return (
            str(source.absolute()),
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    def read(
        self,
        path: str | Path,
        *,
        expected_repo_sha: str,
    ) -> tuple[dict[str, pd.DataFrame], dict, bool]:
        """Return frames, diagnostics and cache-hit flag; never cache BLOCKED."""
        try:
            before = self._signature(path)
        except OSError:
            self._cache_key = None
            self._cache_value = None
            frames, diagnostics = load_futu_us_daily_history_frames(
                path, expected_repo_sha=expected_repo_sha
            )
            return frames, diagnostics, False

        key = (*before, expected_repo_sha)
        if key == self._cache_key and self._cache_value is not None:
            frames, diagnostics = self._cache_value
            return frames, dict(diagnostics), True

        frames, diagnostics = load_futu_us_daily_history_frames(
            path, expected_repo_sha=expected_repo_sha
        )
        try:
            after = self._signature(path)
        except OSError:
            after = None
        if (
            before == after
            and diagnostics.get("status") == "PASS"
        ):
            self._cache_key = key
            self._cache_value = (frames, diagnostics)
        else:
            self._cache_key = None
            self._cache_value = None
        return frames, diagnostics, False
