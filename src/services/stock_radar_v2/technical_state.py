"""Bridge normalized market-data facts into neutral multi-timeframe research state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any, Optional, Sequence

import pandas as pd

from data_provider.market_data_adapter import Bar, SignalPermission
from src.services.realtime_market_data import MarketDataSnapshot
from src.technical.models import MultiTimeframeTechnicalResult, TimeframeState
from src.technical.technical_analyzer import TechnicalAnalyzer


LATEST_ONLY_QUALITY_FLAGS = frozenset(
    {"stale", "historical_query", "delayed_feed", "partial_bar"}
)


@dataclass(frozen=True)
class StockRadarTechnicalState:
    symbol: str
    as_of: datetime
    technical: MultiTimeframeTechnicalResult
    data_health_score: int
    signal_permission: SignalPermission
    provider: Optional[str]
    feed: Optional[str]
    quality_flags: tuple[str, ...] = ()
    research_only: bool = field(default=True, init=False)
    can_confirm_signal: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["signal_permission"] = self.signal_permission.value
        return payload


class StockRadarTechnicalStateService:
    """Evaluate technical facts without creating or confirming a signal."""

    def __init__(self, analyzer: TechnicalAnalyzer | None = None) -> None:
        self._analyzer = analyzer or TechnicalAnalyzer()

    def evaluate(
        self,
        snapshot: MarketDataSnapshot,
        *,
        daily: pd.DataFrame | None = None,
    ) -> StockRadarTechnicalState:
        hourly = _bars_frame(snapshot.bars_1h)
        intraday = _bars_frame(snapshot.bars_15m)
        hourly_partial = _latest_is_partial(snapshot.bars_1h)
        intraday_partial = _latest_is_partial(snapshot.bars_15m)
        result = self._analyzer.analyze(
            snapshot.symbol,
            daily if daily is not None else pd.DataFrame(),
            hourly,
            intraday,
            hourly_partial=hourly_partial,
            intraday_partial=intraday_partial,
        )
        result.hourly = _apply_bar_quality(result.hourly, snapshot.bars_1h)
        result.intraday = _apply_bar_quality(result.intraday, snapshot.bars_15m)
        result.risk_flags = list(
            dict.fromkeys(
                [
                    *result.risk_flags,
                    *result.hourly.quality.warnings,
                    *result.intraday.quality.warnings,
                    *[str(flag).lower() for flag in snapshot.health.quality_flags],
                ]
            )
        )
        return StockRadarTechnicalState(
            symbol=snapshot.symbol,
            as_of=snapshot.as_of,
            technical=result,
            data_health_score=snapshot.health.score,
            signal_permission=snapshot.health.signal_permission,
            provider=snapshot.provider,
            feed=snapshot.feed,
            quality_flags=snapshot.health.quality_flags,
        )


def _bars_frame(bars: Sequence[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": bar.bar_end,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in bars
        ]
    )


def _latest_is_partial(bars: Sequence[Bar]) -> bool:
    return bool(bars and (not bars[-1].is_closed or not bars[-1].is_complete))


def _apply_bar_quality(state: TimeframeState, bars: Sequence[Bar]) -> TimeframeState:
    if not bars:
        return state

    # Currentness/availability flags are temporal. A historical query or stale
    # observation on an older bar must not permanently poison the current
    # timeframe state once a newer clean bar exists. Structural integrity
    # flags still propagate across the full lookback because they can distort
    # the indicator input itself.
    persistent_flags = [
        str(flag).strip().lower()
        for bar in bars
        for flag in bar.quality_flags
        if str(flag).strip()
        and str(flag).strip().lower() not in LATEST_ONLY_QUALITY_FLAGS
    ]
    latest_flags = [
        str(flag).strip().lower()
        for flag in bars[-1].quality_flags
        if str(flag).strip()
        and str(flag).strip().lower() in LATEST_ONLY_QUALITY_FLAGS
    ]
    flags = tuple(dict.fromkeys([*persistent_flags, *latest_flags]))

    warnings = list(dict.fromkeys([*state.quality.warnings, *[f"{state.timeframe}_{flag}" for flag in flags]]))
    partial = _latest_is_partial(bars) or bool(flags)
    quality = replace(
        state.quality,
        status="partial" if partial else state.quality.status,
        is_partial_bar=_latest_is_partial(bars),
        warnings=warnings,
    )
    confidence = min(state.confidence, 0.65) if partial else state.confidence
    return replace(state, confidence=confidence, quality=quality)
