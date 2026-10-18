"""Interpret indicator tables as neutral timeframe states."""

from typing import Optional

import pandas as pd

from .indicators import calculate_indicators
from .models import DataQuality, TimeframeState


def _number(row: pd.Series, key: str) -> Optional[float]:
    value = row.get(key)
    return None if value is None or pd.isna(value) else round(float(value), 4)


def analyze_timeframe(
    df: Optional[pd.DataFrame],
    timeframe: str,
    *,
    include_vwap: bool = False,
    is_partial_bar: bool = False,
) -> TimeframeState:
    if df is None or df.empty:
        return TimeframeState(timeframe=timeframe, quality=DataQuality(
            is_partial_bar=is_partial_bar, warnings=[f"{timeframe}_data_missing"],
        ))
    table = calculate_indicators(df, include_vwap=include_vwap)
    if len(table) < 20:
        return TimeframeState(
            timeframe=timeframe,
            confidence=min(len(table) / 40, 0.45),
            quality=DataQuality(
                status="partial", bars=len(table), is_partial_bar=is_partial_bar,
                as_of=str(table.iloc[-1].get("date")) if "date" in table.columns else None,
                warnings=[f"{timeframe}_insufficient_bars"] + (
                    [f"{timeframe}_partial_bar"] if is_partial_bar else []
                ),
            ),
        )

    latest = table.iloc[-1]
    previous = table.iloc[-2]
    close = float(latest["close"])
    ma5, ma10, ma20 = (_number(latest, key) for key in ("ma5", "ma10", "ma20"))
    if ma5 is not None and ma10 is not None and ma20 is not None and close > ma5 > ma10 > ma20:
        trend, trend_score, ma_text = "bullish", 78, "价格与均线呈多头结构"
    elif ma5 is not None and ma10 is not None and ma20 is not None and close < ma5 < ma10 < ma20:
        trend, trend_score, ma_text = "bearish", 22, "价格与均线呈空头结构"
    else:
        trend, trend_score, ma_text = "neutral", 50, "均线交错或价格处于过渡结构"

    hist = float(latest["macd_hist"])
    previous_hist = float(previous["macd_hist"])
    if hist > 0 and hist > previous_hist:
        momentum = "strengthening"
    elif hist < 0 and hist < previous_hist:
        momentum = "weakening"
    else:
        momentum = "neutral"

    ratio = _number(latest, "volume_ratio")
    if ratio is None:
        volume_state = "unknown"
    elif ratio >= 1.3:
        volume_state = "expanding"
    elif ratio <= 0.7:
        volume_state = "contracting"
    else:
        volume_state = "normal"
    supertrend_up = int(latest["supertrend_direction"]) > 0
    momentum_adjustment = 7 if momentum == "strengthening" else -7 if momentum == "weakening" else 0
    score = trend_score + (8 if supertrend_up else -8) + momentum_adjustment
    score = max(0, min(100, score))
    confidence = min(0.95, 0.55 + len(table) / 400)
    warnings = []
    if is_partial_bar:
        confidence = min(confidence, 0.65)
        warnings.append(f"{timeframe}_partial_bar")
    as_of = str(table.iloc[-1].get("date")) if "date" in table.columns else None
    summary = f"{ma_text}；动能{ {'strengthening': '增强', 'weakening': '减弱'}.get(momentum, '中性') }"
    return TimeframeState(
        timeframe=timeframe,
        trend=trend,
        momentum=momentum,
        volume_state=volume_state,
        structure_score=score,
        confidence=round(confidence, 2),
        summary=summary,
        indicators={
            "close": close,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": _number(latest, "ma60"),
            "macd": _number(latest, "macd"),
            "macd_signal": _number(latest, "macd_signal"),
            "rsi14": _number(latest, "rsi14"),
            "atr14": _number(latest, "atr14"),
            "vwap": _number(latest, "vwap"),
            "volume_ratio": ratio,
            "supertrend": _number(latest, "supertrend"),
        },
        evidence=[ma_text, f"SuperTrend={'多' if supertrend_up else '空'}", f"MACD动能={momentum}"],
        quality=DataQuality(
            status="partial" if is_partial_bar else "ok",
            bars=len(table),
            as_of=as_of,
            is_partial_bar=is_partial_bar,
            warnings=warnings,
        ),
    )
