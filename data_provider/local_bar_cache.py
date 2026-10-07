"""Persistent research-only cache for closure-proven market bars.

This cache is intentionally downstream of canonical/provider qualification.
It never fetches data, never promotes bars to canonical status, and never
changes trading permissions. Only bars explicitly marked closed + complete
are accepted.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator
import zlib


_SCHEMA = """
CREATE TABLE IF NOT EXISTS settled_bars (
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bar_end_utc TEXT NOT NULL,
    bar_start_utc TEXT,
    provider TEXT,
    payload_zlib BLOB NOT NULL,
    raw_bytes INTEGER NOT NULL,
    compressed_bytes INTEGER NOT NULL,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (market, symbol, timeframe, bar_end_utc)
);
CREATE INDEX IF NOT EXISTS idx_settled_bars_lookup
ON settled_bars (market, symbol, timeframe, bar_end_utc DESC);
"""


class SettledBarCache:
    """SQLite + zlib cache for already-settled bars."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _aware_iso(value: object, *, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a timezone-aware ISO timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a timezone-aware ISO timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")
        return parsed.astimezone(timezone.utc).isoformat()

    @classmethod
    def _normalize_bar(cls, bar: object) -> dict:
        if not isinstance(bar, dict):
            raise ValueError("bar must be a dict")
        if bar.get("is_closed") is not True or bar.get("is_complete") is not True:
            raise ValueError("bar is not closure-proven settled data")

        market = str(bar.get("market") or "").strip().lower()
        symbol = str(bar.get("symbol") or "").strip().upper()
        timeframe = str(bar.get("timeframe") or "").strip().lower()
        if not market or not symbol or not timeframe:
            raise ValueError("market, symbol and timeframe are required")

        bar_end_utc = cls._aware_iso(bar.get("bar_end_utc"), field="bar_end_utc")
        bar_start = bar.get("bar_start_utc")
        bar_start_utc = (
            cls._aware_iso(bar_start, field="bar_start_utc")
            if bar_start not in (None, "")
            else None
        )

        normalized = dict(bar)
        normalized["market"] = market
        normalized["symbol"] = symbol
        normalized["timeframe"] = timeframe
        normalized["bar_end_utc"] = bar_end_utc
        if bar_start_utc is not None:
            normalized["bar_start_utc"] = bar_start_utc
        return normalized

    def upsert_bars(self, bars: Iterable[object]) -> dict:
        accepted = 0
        rejected: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            for index, raw_bar in enumerate(bars):
                try:
                    bar = self._normalize_bar(raw_bar)
                except ValueError as exc:
                    rejected.append({"index": index, "error": str(exc)})
                    continue

                raw_payload = json.dumps(
                    bar,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                compressed = zlib.compress(raw_payload, level=6)
                conn.execute(
                    """
                    INSERT INTO settled_bars (
                        market, symbol, timeframe, bar_end_utc, bar_start_utc,
                        provider, payload_zlib, raw_bytes, compressed_bytes,
                        updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(market, symbol, timeframe, bar_end_utc)
                    DO UPDATE SET
                        bar_start_utc=excluded.bar_start_utc,
                        provider=excluded.provider,
                        payload_zlib=excluded.payload_zlib,
                        raw_bytes=excluded.raw_bytes,
                        compressed_bytes=excluded.compressed_bytes,
                        updated_at_utc=excluded.updated_at_utc
                    """,
                    (
                        bar["market"],
                        bar["symbol"],
                        bar["timeframe"],
                        bar["bar_end_utc"],
                        bar.get("bar_start_utc"),
                        bar.get("provider"),
                        compressed,
                        len(raw_payload),
                        len(compressed),
                        now,
                    ),
                )
                accepted += 1

        return {
            "accepted": accepted,
            "rejected": rejected,
            "cache_path": str(self.path),
            "research_only": True,
            "canonical_authority": False,
            "live_trade": False,
        }

    def read_bars(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        before_bar_end_utc: str | None = None,
    ) -> list[dict]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")

        market_key = market.strip().lower()
        symbol_key = symbol.strip().upper()
        timeframe_key = timeframe.strip().lower()
        if not market_key or not symbol_key or not timeframe_key:
            raise ValueError("market, symbol and timeframe are required")

        params: list[object] = [market_key, symbol_key, timeframe_key]
        where = "market=? AND symbol=? AND timeframe=?"
        if before_bar_end_utc is not None:
            where += " AND bar_end_utc < ?"
            params.append(self._aware_iso(before_bar_end_utc, field="before_bar_end_utc"))
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT payload_zlib
                FROM settled_bars
                WHERE {where}
                ORDER BY bar_end_utc DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        decoded = [
            json.loads(zlib.decompress(row[0]).decode("utf-8"))
            for row in rows
        ]
        decoded.reverse()
        return decoded

    def stats(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(raw_bytes), 0),
                       COALESCE(SUM(compressed_bytes), 0)
                FROM settled_bars
                """
            ).fetchone()
        count, raw_bytes, compressed_bytes = row
        ratio = (compressed_bytes / raw_bytes) if raw_bytes else None
        return {
            "bar_count": int(count),
            "raw_bytes": int(raw_bytes),
            "compressed_bytes": int(compressed_bytes),
            "compression_ratio": ratio,
            "cache_path": str(self.path),
            "research_only": True,
            "canonical_authority": False,
            "live_trade": False,
        }
