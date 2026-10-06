from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

@dataclass(frozen=True)
class FormingMinuteBar:
    symbol: str
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float | None
    is_closed: bool

class FutuK1MFormingAccumulator:
    """Collapse repeated OpenD K_1M updates into one minute; close only on next minute evidence."""
    def __init__(self) -> None:
        self._current: dict[str, FormingMinuteBar] = {}

    def ingest(self, payload: Mapping[str, object]) -> tuple[FormingMinuteBar | None, FormingMinuteBar]:
        symbol=str(payload.get("code") or "").strip()
        raw=str(payload.get("time_key") or "").strip()
        if not symbol.startswith("US.") or not raw:
            raise ValueError("canonical US code and time_key are required")
        start=datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        bar=FormingMinuteBar(symbol,start,float(payload["open"]),float(payload["high"]),float(payload["low"]),float(payload["close"]),float(payload.get("volume") or 0),float(payload["turnover"]) if payload.get("turnover") is not None else None,False)
        prior=self._current.get(symbol)
        if prior is not None and start < prior.start:
            raise ValueError("out-of-order K_1M time_key")
        if prior is not None and start == prior.start:
            self._current[symbol]=bar
            return None,bar
        closed=None
        if prior is not None:
            closed=FormingMinuteBar(prior.symbol,prior.start,prior.open,prior.high,prior.low,prior.close,prior.volume,prior.turnover,True)
        self._current[symbol]=bar
        return closed,bar

    def current(self, symbol: str) -> FormingMinuteBar | None:
        return self._current.get(symbol)
