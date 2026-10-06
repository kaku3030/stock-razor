from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True)
class FormingMinuteBar:
    symbol: str
    end_label: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float | None
    is_closed: bool

    @property
    def start(self) -> datetime:
        """Backward-compatible raw provider label; not canonical bar_start."""
        return self.end_label


class FutuK1MFormingAccumulator:
    """Collapse repeated OpenD K_1M updates; close only on later label evidence.

    AWS cross-check evidence on 2026-10-06 showed US intraday K_1M/K_5M labels
    are bar-end labels (regular sessions end at 16:00). This accumulator keeps
    that provider label unchanged; canonical interval conversion happens in the
    research bridge.
    """

    def __init__(self) -> None:
        self._current: dict[str, FormingMinuteBar] = {}

    def ingest(
        self, payload: Mapping[str, object]
    ) -> tuple[FormingMinuteBar | None, FormingMinuteBar]:
        symbol = str(payload.get("code") or "").strip()
        raw = str(payload.get("time_key") or "").strip()
        if not symbol.startswith("US.") or not raw:
            raise ValueError("canonical US code and time_key are required")
        end_label = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        bar = FormingMinuteBar(
            symbol,
            end_label,
            float(payload["open"]),
            float(payload["high"]),
            float(payload["low"]),
            float(payload["close"]),
            float(payload.get("volume") or 0),
            float(payload["turnover"]) if payload.get("turnover") is not None else None,
            False,
        )
        prior = self._current.get(symbol)
        if prior is not None and end_label < prior.end_label:
            raise ValueError("out-of-order K_1M time_key")
        if prior is not None and end_label == prior.end_label:
            self._current[symbol] = bar
            return None, bar
        closed = None
        if prior is not None:
            closed = FormingMinuteBar(
                prior.symbol,
                prior.end_label,
                prior.open,
                prior.high,
                prior.low,
                prior.close,
                prior.volume,
                prior.turnover,
                True,
            )
        self._current[symbol] = bar
        return closed, bar

    def current(self, symbol: str) -> FormingMinuteBar | None:
        return self._current.get(symbol)
