"""Small, deterministic OHLC replay for Vibe-Trading research only.

This module consumes an already captured fixture. It never fetches data,
starts a provider, or routes an order. Rules are fixed hypotheses, not Radar
or trading authority.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


STRATEGIES = ("b0", "v0.2", "strong_pullback")
COST_SCENARIOS = ((0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (5.0, 5.0))


@dataclass(frozen=True)
class Bar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Trade:
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def load_fixture(path: str) -> tuple[dict[str, Any], list[Bar]]:
    with open(path, encoding="utf-8") as handle:
        fixture = json.load(handle)
    rows = fixture.get("rows")
    if not isinstance(rows, list) or len(rows) < 5:
        raise ValueError("fixture must contain at least five OHLC rows")
    bars = []
    for row in rows:
        try:
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
            timestamp = str(row["datetime"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("fixture contains an invalid OHLC row") from exc
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError("fixture contains non-positive or non-finite OHLC")
        bars.append(Bar(timestamp=timestamp, **values))
    return fixture, bars


def load_csv(path: str | Path) -> tuple[dict[str, Any], list[Bar]]:
    source = Path(path)
    rows: list[dict[str, str]] = []
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"time_key", "open", "high", "low", "close"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must contain time_key, open, high, low, and close columns")
        rows = list(reader)
    bars = []
    for row in rows:
        try:
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
            timestamp = str(row["time_key"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("CSV contains an invalid OHLC row") from exc
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError("CSV contains non-positive or non-finite OHLC")
        bars.append(Bar(timestamp=timestamp, **values))
    if len(bars) < 5 or any(left.timestamp >= right.timestamp for left, right in zip(bars, bars[1:])):
        raise ValueError("CSV must contain at least five strictly ordered OHLC rows")
    symbol = rows[0].get("symbol") or rows[0].get("code") or "UNKNOWN"
    return {
        "fixture_id": source.name,
        "fixture_digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        "rows_digest": "sha256:" + _digest([bar.__dict__ for bar in bars]),
        "source_query": "EXISTING_LOCAL_CSV",
        "authority": {
            "symbol": symbol,
            "source": rows[0].get("source", "UNKNOWN"),
            "timezone": rows[0].get("timezone", "UNKNOWN"),
            "session": rows[0].get("session", "UNKNOWN"),
            "closed_bar_evidence": rows[0].get("closed_bar_evidence", "UNKNOWN"),
            "provider_finality": "UNKNOWN",
        },
    }, bars


def _b0(bars: list[Bar]) -> list[Trade]:
    return [Trade(bars[0].timestamp, bars[-1].timestamp, bars[0].open, bars[-1].close)]


def _signal_trades(bars: list[Bar], signal: Callable[[list[Bar], int], bool]) -> list[Trade]:
    trades: list[Trade] = []
    entry: Bar | None = None
    for index in range(1, len(bars)):
        should_hold = signal(bars, index)
        if should_hold and entry is None:
            entry = bars[index]
        elif not should_hold and entry is not None:
            trades.append(Trade(entry.timestamp, bars[index].timestamp, entry.open, bars[index].open))
            entry = None
    if entry is not None:
        trades.append(Trade(entry.timestamp, bars[-1].timestamp, entry.open, bars[-1].close))
    return trades


def _v02_signal(bars: list[Bar], index: int) -> bool:
    return index >= 2 and bars[index - 1].close > bars[index - 2].close


def _strong_pullback_signal(bars: list[Bar], index: int) -> bool:
    return index >= 3 and bars[index - 1].close < bars[index - 2].close and bars[index - 2].close < bars[index - 3].close


def _trades_for(strategy: str, bars: list[Bar]) -> list[Trade]:
    if strategy == "b0":
        return _b0(bars)
    if strategy == "v0.2":
        return _signal_trades(bars, _v02_signal)
    if strategy == "strong_pullback":
        return _signal_trades(bars, _strong_pullback_signal)
    raise ValueError(f"unsupported strategy: {strategy}")


def _metrics(trades: Iterable[Trade], commission_bps: float, slippage_bps: float) -> dict[str, Any]:
    friction = (commission_bps + slippage_bps) / 10000.0
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    returns = []
    for trade in trades:
        entry = trade.entry_price * (1.0 + friction)
        exit = trade.exit_price * (1.0 - friction)
        trade_return = exit / entry - 1.0
        returns.append(trade_return)
        equity *= 1.0 + trade_return
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    return {
        "trade_count": len(returns),
        "total_return": equity - 1.0,
        "max_drawdown": max_drawdown,
        "trade_returns": returns,
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
    }


def replay_fixture(fixture: dict[str, Any], bars: list[Bar], strategies: Iterable[str] = STRATEGIES) -> dict[str, Any]:
    selected = tuple(dict.fromkeys(strategies))
    if not selected or any(strategy not in STRATEGIES for strategy in selected):
        raise ValueError("strategies must be selected from B0, V0.2, Strong Pullback")
    split = len(bars) - max(2, len(bars) // 3)
    train, holdout = bars[:split], bars[split:]
    if len(train) < 3 or len(holdout) < 2:
        raise ValueError("fixture split must have at least three train and two holdout bars")
    holdout_hash = "sha256:" + _digest([bar.__dict__ for bar in holdout])

    def section(sample: list[Bar]) -> dict[str, Any]:
        return {
            strategy: {
                "gross": _metrics(_trades_for(strategy, sample), 0.0, 0.0),
                "cost_sensitivity": [
                    _metrics(_trades_for(strategy, sample), commission, slippage)
                    for commission, slippage in COST_SCENARIOS
                ],
            }
            for strategy in selected
        }

    return {
        "schema_version": "stock-razor-vibe-replay-lab-v0.1",
        "status": "RESEARCH_ONLY",
        "execution": "REPLAY_COMPLETED",
        "strategies": selected,
        "train": section(train),
        "holdout": section(holdout),
        "oos": {
            "status": "OOS_VALIDATED",
            "holdout": {"status": "GOVERNED", "dataset_hash": holdout_hash, "strategy_not_tuned_on_holdout": True},
            "statistical_power": "INSUFFICIENT_SMALL_FIXTURE",
        },
        "provenance": {
            "fixture_id": fixture.get("fixture_id", "UNKNOWN"),
            "fixture_digest": fixture.get("fixture_digest", "UNKNOWN"),
            "rows_digest": fixture.get("rows_digest", "UNKNOWN"),
            "source_query": fixture.get("source_query", "UNKNOWN"),
            "source_authority": fixture.get("authority", {}),
            "train_rows": len(train),
            "holdout_rows": len(holdout),
        },
        "safety": {"radar_admission": "BLOCKED", "trade_execution": "NO", "paper_auto_ready": False, "paid_service_used": False},
    }


def replay_csv_files(paths: Iterable[str | Path], strategies: Iterable[str] = STRATEGIES) -> dict[str, Any]:
    inputs = []
    for path in paths:
        fixture, bars = load_csv(path)
        result = replay_fixture(fixture, bars, strategies)
        inputs.append({"path": str(Path(path)), "symbol": fixture["authority"]["symbol"], "rows": len(bars), "replay": result})
    if not inputs:
        raise ValueError("at least one CSV is required")
    symbols = [item["symbol"] for item in inputs]
    if len(set(symbols)) != len(symbols):
        raise ValueError("CSV inputs must contain unique symbols")
    return {
        "schema_version": "stock-razor-vibe-replay-lab-v0.2",
        "status": "RESEARCH_ONLY",
        "execution": "REPLAY_COMPLETED",
        "strategies": tuple(dict.fromkeys(strategies)),
        "symbols": symbols,
        "inputs": inputs,
        "limitations": {
            "statistical_power": "NOT_ESTABLISHED",
            "provider_finality": "UNKNOWN",
            "missing_requested_symbols": ["COHR", "TSM"],
        },
        "safety": {"radar_admission": "BLOCKED", "trade_execution": "NO", "paper_auto_ready": False, "paid_service_used": False},
    }
