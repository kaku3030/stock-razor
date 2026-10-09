"""Pure indicator calculations with no trading decisions."""

from typing import Iterable

import numpy as np
import pandas as pd


REQUIRED_OHLCV = ("open", "high", "low", "close", "volume")


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=("date", *REQUIRED_OHLCV))
    result = df.copy()
    result.columns = [str(column).lower() for column in result.columns]
    if "date" not in result.columns and isinstance(result.index, pd.DatetimeIndex):
        result = result.reset_index().rename(columns={result.index.name or "index": "date"})
    missing = [column for column in REQUIRED_OHLCV if column not in result.columns]
    if missing:
        raise ValueError(f"OHLCV missing required columns: {', '.join(missing)}")
    for column in REQUIRED_OHLCV:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=["close"]).reset_index(drop=True)
    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        result = result.sort_values("date").reset_index(drop=True)
    return result


def add_moving_averages(df: pd.DataFrame, periods: Iterable[int] = (5, 10, 20, 60)) -> pd.DataFrame:
    result = df.copy()
    for period in periods:
        result[f"ma{period}"] = result["close"].rolling(period, min_periods=period).mean()
    return result


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    result = df.copy()
    fast_ema = result["close"].ewm(span=fast, adjust=False).mean()
    slow_ema = result["close"].ewm(span=slow, adjust=False).mean()
    result["macd"] = fast_ema - slow_ema
    result["macd_signal"] = result["macd"].ewm(span=signal, adjust=False).mean()
    result["macd_hist"] = result["macd"] - result["macd_signal"]
    return result


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    result = df.copy()
    delta = result["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    result[f"rsi{period}"] = (100 - 100 / (1 + rs)).fillna(50.0)
    return result


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    result = df.copy()
    previous_close = result["close"].shift(1)
    true_range = pd.concat(
        [
            result["high"] - result["low"],
            (result["high"] - previous_close).abs(),
            (result["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    result[f"atr{period}"] = true_range.ewm(alpha=1 / period, adjust=False).mean()
    return result


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    typical_price = (result["high"] + result["low"] + result["close"]) / 3
    volume = result["volume"].fillna(0).clip(lower=0)
    denominator = volume.cumsum().replace(0, np.nan)
    result["vwap"] = (typical_price * volume).cumsum() / denominator
    return result


def add_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    result = add_atr(df, period)
    midpoint = (result["high"] + result["low"]) / 2
    upper = midpoint + multiplier * result[f"atr{period}"]
    lower = midpoint - multiplier * result[f"atr{period}"]
    # Keep the exact historical state machine, but replace repeated Pandas
    # scalar .at lookups with NumPy array indexing. Each series conversion is
    # done once; do not change the ATR formula, transition order, NaN handling
    # (Python's max/min), or the signal direction semantics.
    upper_values = upper.to_numpy(copy=True)
    lower_values = lower.to_numpy(copy=True)
    close_values = result["close"].to_numpy(copy=False)
    direction_values = np.ones(len(result), dtype=np.int64)
    line_values = lower_values.copy()
    for index in range(1, len(result)):
        previous = index - 1
        if close_values[index] > upper_values[previous]:
            direction_values[index] = 1
        elif close_values[index] < lower_values[previous]:
            direction_values[index] = -1
        else:
            direction_values[index] = direction_values[previous]
            if direction_values[index] > 0:
                lower_values[index] = max(lower_values[index], lower_values[previous])
            else:
                upper_values[index] = min(upper_values[index], upper_values[previous])
        line_values[index] = (
            lower_values[index] if direction_values[index] > 0 else upper_values[index]
        )
    result["supertrend"] = line_values
    result["supertrend_direction"] = direction_values
    return result


def calculate_indicators(df: pd.DataFrame, *, include_vwap: bool = False) -> pd.DataFrame:
    result = normalize_ohlcv(df)
    if result.empty:
        return result
    result = add_moving_averages(result)
    result = add_macd(result)
    result = add_rsi(result)
    result = add_atr(result)
    result = add_supertrend(result)
    result["volume_ma20"] = result["volume"].rolling(20, min_periods=5).mean()
    result["volume_ratio"] = result["volume"] / result["volume_ma20"].replace(0, np.nan)
    if include_vwap:
        result = add_vwap(result)
    return result
