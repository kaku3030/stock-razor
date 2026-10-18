"""Deterministic research-only portfolio accounting.

The engine keeps shares and cash explicitly. Target weights are only applied
on rows marked for rebalancing; all other rows let holdings drift with prices.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd


def _validate_prices(prices: pd.DataFrame) -> None:
    if prices.empty or not prices.index.is_monotonic_increasing or not prices.index.is_unique:
        raise ValueError("prices must have a non-empty, sorted, unique index")
    if prices.isna().any().any() or (~prices.map(lambda value: math.isfinite(float(value)))).any().any():
        raise ValueError("prices must contain only finite values")
    if (prices <= 0).any().any():
        raise ValueError("prices must be positive")


def replay_portfolio(
    prices: pd.DataFrame,
    target_weights: pd.DataFrame,
    rebalance: pd.Series,
    fee_bps: float,
    slippage_bps: float,
    *,
    dividend_assumption: str = "QFQ close only; distributions not independently modeled",
) -> pd.DataFrame:
    """Replay one portfolio with explicit shares, cash, costs and drift.

    ``target_weights`` contains the desired allocation for every date, while
    ``rebalance`` controls the only dates on which the desired allocation is
    applied. The first row must rebalance. We use close-to-close returns and do
    not invent a dividend cash flow; the QFQ semantic remains UNKNOWN.
    """
    _validate_prices(prices)
    if not prices.columns.is_unique or list(target_weights.columns) != list(prices.columns):
        raise ValueError("target weights must have exactly the price columns")
    if not target_weights.index.equals(prices.index) or not rebalance.index.equals(prices.index):
        raise ValueError("prices, target weights and rebalance mask must share the exact index")
    if target_weights.isna().any().any() or (target_weights < 0).any().any():
        raise ValueError("target weights must be finite and non-negative")
    if (~target_weights.map(lambda value: math.isfinite(float(value)))).any().any():
        raise ValueError("target weights must be finite")
    if (target_weights.sum(axis=1) > 1.0 + 1e-12).any():
        raise ValueError("target weights cannot exceed 100 percent")
    if not bool(rebalance.iloc[0]):
        raise ValueError("the first row must rebalance")

    cost_rate = (float(fee_bps) + float(slippage_bps)) / 10000.0
    shares = pd.Series(0.0, index=prices.columns)
    cash = 0.0
    previous_nav = 1.0
    rows: list[dict[str, object]] = []

    previous_prices: pd.Series | None = None
    for date in prices.index:
        row_prices = prices.loc[date].astype(float)
        valuation_prices = row_prices if previous_prices is None else previous_prices
        start_asset_values = shares * valuation_prices
        start_nav = float(start_asset_values.sum() + cash)
        if not rows:
            start_nav = previous_nav
        target = target_weights.loc[date].astype(float)
        turnover = 0.0
        transaction_cost = 0.0
        if bool(rebalance.loc[date]):
            pre_trade_weights = start_asset_values / start_nav if start_nav else start_asset_values * 0.0
            turnover = float((target - pre_trade_weights).abs().sum())
            transaction_cost = start_nav * turnover * cost_rate
            investable_nav = start_nav - transaction_cost
            shares = target * investable_nav / valuation_prices
            cash = (1.0 - float(target.sum())) * investable_nav
        end_asset_values = shares * row_prices
        nav = float(end_asset_values.sum() + cash)
        gross_return = (nav + transaction_cost) / start_nav - 1.0 if start_nav else 0.0
        net_return = nav / start_nav - 1.0 if start_nav else 0.0
        actual_weights = end_asset_values / nav if nav else end_asset_values * 0.0
        record: dict[str, object] = {
            "date": date,
            "start_nav": start_nav,
            "nav": nav,
            "cash": float(cash),
            "target_weight_sum": float(target.sum()),
            "cash_weight": float(cash / nav) if nav else 0.0,
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "gross_return": gross_return,
            "net_return": net_return,
            "rebalanced": bool(rebalance.loc[date]),
            "dividend_assumption": dividend_assumption,
        }
        record.update({f"price_{symbol}": float(value) for symbol, value in row_prices.items()})
        record.update({f"target_weight_{symbol}": float(value) for symbol, value in target.items()})
        record.update({f"shares_{symbol}": float(value) for symbol, value in shares.items()})
        record.update({f"actual_weight_{symbol}": float(value) for symbol, value in actual_weights.items()})
        rows.append(record)
        previous_nav = nav
        previous_prices = row_prices

    return pd.DataFrame(rows).set_index("date")


def target_schedule(
    prices: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    state: pd.Series | None = None,
    state_weights: Mapping[str, Mapping[str, float]] | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build a target schedule and state-change-only rebalance mask."""
    if state is None:
        target = pd.DataFrame([weights] * len(prices), index=prices.index).reindex(columns=prices.columns, fill_value=0.0).fillna(0.0)
        return target.astype(float), pd.Series([True] + [False] * (len(prices) - 1), index=prices.index)
    if state_weights is None or not state.index.equals(prices.index):
        raise ValueError("state and state_weights are required with the exact price index")
    target = pd.DataFrame(
        [state_weights[str(value)] for value in state], index=prices.index
    ).reindex(columns=prices.columns, fill_value=0.0).fillna(0.0).astype(float)
    return target, state.ne(state.shift()).fillna(True).astype(bool)
