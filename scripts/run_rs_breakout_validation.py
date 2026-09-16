#!/usr/bin/env python3
"""Independent, research-only RS Breakout validation runner.

The runner consumes recorded capture evidence and never calls a live provider.
It validates capture hashes/status, uses only information available at the
decision bar, and emits an auditable report.  It does not register experiments,
claim or burn a Never-Seen Holdout, or authorize production use.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")


class ValidationError(ValueError):
    """Raised when recorded evidence or the research contract is invalid."""


@dataclass(frozen=True)
class Bar:
    symbol: str
    day: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"JSON object required: {path}")
    return payload


def _validate_contract(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema") != "radar-rs-breakout-hypothesis-v0.1":
        raise ValidationError("unexpected RS hypothesis schema")
    if payload.get("status") != "RESEARCH_ONLY":
        raise ValidationError("RS validation requires RESEARCH_ONLY status")
    provenance = payload.get("provenance", {})
    if provenance.get("production_authorized") is not False:
        raise ValidationError("production_authorized must remain false")
    params = payload.get("parameters", {})
    checks = {
        "breakout_window_bars": lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 2,
        "volume_multiple": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0,
        "relative_strength_percentile": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 < value <= 100,
        "holding_period_bars": lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 1,
    }
    for name, predicate in checks.items():
        if name not in params or not predicate(params[name]):
            raise ValidationError(f"invalid parameter: {name}")
    required = {"WITH_RULE", "WITHOUT_RULE", "SHUFFLED_PLACEBO", "DELAYED_RULE", "REGIME_CONDITIONED"}
    if set(payload.get("required_counterfactuals", [])) != required:
        raise ValidationError("counterfactual contract is incomplete or changed")
    holdout = payload.get("holdout_policy", {})
    if holdout.get("never_seen_holdout") != "PROTECTED" or holdout.get("consumes_holdout") is not False:
        raise ValidationError("Never-Seen Holdout policy must remain protected and non-consuming")
    return payload


def _load_captures(input_dir: Path) -> dict[str, dict[str, Bar]]:
    series: dict[str, dict[str, Bar]] = {}
    for csv_path in sorted(input_dir.glob("*.csv")):
        if csv_path.stem.endswith("_akshare"):
            continue
        manifest_path = Path(f"{csv_path}.manifest.json")
        if not manifest_path.is_file():
            raise ValidationError(f"missing capture manifest: {manifest_path}")
        manifest = _read_json(manifest_path)
        if manifest.get("status") != "CAPTURED_NOT_APPROVED":
            raise ValidationError(f"capture is not recorded evidence: {csv_path}")
        if manifest.get("raw_sha256") != hashlib.sha256(csv_path.read_bytes()).hexdigest():
            raise ValidationError(f"capture hash mismatch: {csv_path}")
        try:
            with csv_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
                    raise ValidationError(f"unexpected capture columns: {csv_path}")
                rows: dict[str, Bar] = {}
                capture_symbol: str | None = None
                for row_number, row in enumerate(reader, start=2):
                    symbol = row["symbol"].strip()
                    if not symbol:
                        raise ValidationError(f"empty symbol in capture: {csv_path}:{row_number}")
                    if capture_symbol is None:
                        capture_symbol = symbol
                    elif symbol != capture_symbol:
                        raise ValidationError(f"mixed symbols in capture: {csv_path}:{row_number}")
                    day = date.fromisoformat(row["date"]).isoformat()
                    open_price = float(row["open"])
                    high = float(row["high"])
                    low = float(row["low"])
                    close = float(row["close"])
                    volume = float(row["volume"])
                    if not all(math.isfinite(value) for value in (open_price, high, low, close, volume)):
                        raise ValidationError(f"non-finite bar at {csv_path}:{row_number}")
                    if open_price <= 0 or high <= 0 or low <= 0 or close <= 0 or volume < 0:
                        raise ValidationError(f"invalid OHLCV at {csv_path}:{row_number}")
                    if high < max(open_price, low, close) or low > min(open_price, close):
                        raise ValidationError(f"inconsistent OHLC at {csv_path}:{row_number}")
                    if day in rows:
                        raise ValidationError(f"duplicate date/symbol at {csv_path}:{row_number}")
                    rows[day] = Bar(symbol, day, open_price, high, low, close, volume)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(f"malformed capture: {csv_path}: {exc}") from exc
        if len(rows) < 2:
            raise ValidationError(f"capture must contain at least two rows: {csv_path}")
        if list(rows) != sorted(rows):
            raise ValidationError(f"capture dates must be chronological: {csv_path}")
        series[csv_path.stem] = rows
    if len(series) < 2:
        raise ValidationError("at least two primary symbols are required for cross-sectional RS")
    return series


def _rank_percentiles(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = max(1, len(ordered) - 1)
    return {symbol: 100.0 * index / denominator for index, (symbol, _) in enumerate(ordered)}


def _aggregate(
    observations: list[dict[str, Any]],
    flags: list[bool],
    round_trip_cost_bps: float,
) -> dict[str, Any]:
    selected = [item["forward_return"] for item, flag in zip(observations, flags) if flag]
    cost_factor = 1.0 - round_trip_cost_bps / 10000.0
    net_selected = [(1.0 + value) * cost_factor - 1.0 for value in selected]
    gross_equity = 1.0
    net_equity = 1.0
    for gross_value, net_value in zip(selected, net_selected):
        gross_equity *= 1.0 + gross_value
        net_equity *= 1.0 + net_value
    return {
        "observations": len(observations),
        "selected_count": len(selected),
        "coverage": len(selected) / len(observations) if observations else 0.0,
        "average_forward_return": sum(selected) / len(selected) if selected else None,
        "average_net_forward_return": sum(net_selected) / len(net_selected) if net_selected else None,
        "cumulative_forward_return": gross_equity - 1.0 if selected else None,
        "cumulative_net_forward_return": net_equity - 1.0 if net_selected else None,
        "round_trip_cost_bps": round_trip_cost_bps,
        "win_rate": sum(value > 0 for value in selected) / len(selected) if selected else None,
        "net_win_rate": sum(value > 0 for value in net_selected) / len(net_selected) if net_selected else None,
    }


def _build_observations(series: dict[str, dict[str, Bar]], params: dict[str, Any]) -> list[dict[str, Any]]:
    lookback = params["breakout_window_bars"]
    hold_bars = params["holding_period_bars"]
    volume_multiple = float(params["volume_multiple"])
    percentile_threshold = float(params["relative_strength_percentile"])
    common_dates = sorted(set.intersection(*(set(rows) for rows in series.values())))
    if not common_dates:
        return []
    first = max(lookback, 1)
    # A close-based signal can only be executed at the next bar open.
    last = len(common_dates) - hold_bars - 1
    observations: list[dict[str, Any]] = []
    for index in range(first, max(first, last)):
        day = common_dates[index]
        entry_day = common_dates[index + 1]
        exit_day = common_dates[index + 1 + hold_bars]
        rs_values = {
            symbol: series[symbol][day].close / series[symbol][common_dates[index - lookback]].close - 1.0
            for symbol in series
        }
        percentiles = _rank_percentiles(rs_values)
        market_return = sum(rs_values.values()) / len(rs_values)
        for symbol, rows in sorted(series.items()):
            bar = rows[day]
            prior_bars = [rows[common_dates[pos]] for pos in range(index - lookback, index)]
            average_volume = sum(item.volume for item in prior_bars) / len(prior_bars)
            breakout = bar.close > max(item.high for item in prior_bars)
            volume_ok = average_volume > 0 and bar.volume >= average_volume * volume_multiple
            selected = breakout and volume_ok and percentiles[symbol] >= percentile_threshold
            observations.append({
                "date": day,
                "symbol": symbol,
                "forward_return": rows[exit_day].close / rows[entry_day].open - 1.0,
                "with_rule": selected,
                "regime": "risk_on" if market_return >= 0 else "risk_off",
                "rs_percentile": round(percentiles[symbol], 6),
                "breakout": breakout,
                "volume_multiple": round(bar.volume / average_volume, 6) if average_volume > 0 else None,
            })
    return observations


def _split_name(index: int, dates: list[str]) -> str:
    first = len(dates) // 3
    second = (2 * len(dates)) // 3
    if index < first:
        return "development"
    if index < second:
        return "validation"
    return "never_seen_holdout"


def run_validation(
    input_dir: Path,
    contract_path: Path,
    output_path: Path,
    *,
    seed: int = 20260915,
    round_trip_cost_bps: float = 0.0,
) -> dict[str, Any]:
    if not math.isfinite(round_trip_cost_bps) or round_trip_cost_bps < 0 or round_trip_cost_bps > 10000:
        raise ValidationError("round_trip_cost_bps must be finite and between 0 and 10000")
    contract = _validate_contract(contract_path)
    series = _load_captures(input_dir)
    observations = _build_observations(series, contract["parameters"])
    if not observations:
        raise ValidationError("no eligible observations for the configured lookback/holding period")
    dates = sorted({item["date"] for item in observations})
    with_flags = [bool(item["with_rule"]) for item in observations]
    without_flags = [True] * len(observations)
    delayed_flags = []
    selected_by_symbol_date = {(item["symbol"], item["date"]): item["with_rule"] for item in observations}
    date_index = {day: index for index, day in enumerate(sorted(set(item["date"] for item in observations)))}
    for item in observations:
        previous = date_index[item["date"]] - 1
        previous_day = dates[previous] if previous >= 0 else None
        delayed_flags.append(bool(previous_day and selected_by_symbol_date.get((item["symbol"], previous_day), False)))
    placebo_flags = with_flags[:]
    random.Random(seed).shuffle(placebo_flags)
    regime_flags = [flag and item["regime"] == "risk_on" for item, flag in zip(observations, with_flags)]
    variants = {
        "WITH_RULE": with_flags,
        "WITHOUT_RULE": without_flags,
        "SHUFFLED_PLACEBO": placebo_flags,
        "DELAYED_RULE": delayed_flags,
        "REGIME_CONDITIONED": regime_flags,
    }
    splits: dict[str, dict[str, list[int]]] = {}
    for position, item in enumerate(observations):
        splits.setdefault(_split_name(date_index[item["date"]], dates), {}).setdefault(item["date"], []).append(position)
    metrics: dict[str, Any] = {}
    for name, flags in variants.items():
        metrics[name] = {"overall": _aggregate(observations, flags, round_trip_cost_bps), "splits": {}}
        for split, split_dates in splits.items():
            positions = [position for day in split_dates for position in range(len(observations)) if observations[position]["date"] == day]
            metrics[name]["splits"][split] = _aggregate(
                [observations[position] for position in positions],
                [flags[position] for position in positions],
                round_trip_cost_bps,
            )
    result = {
        "schema": "radar-rs-breakout-validation-v0.1",
        "status": "RESEARCH_ONLY",
        "rule_id": contract["rule_id"],
        "source": {
            "input_dir": str(input_dir),
            "symbols": sorted(series),
            "capture_count": len(series),
            "dates": len(dates),
        },
        "guard": {
            "pit": "RECORDED_CAPTURE_ONLY",
            "signal_execution": "NEXT_BAR_OPEN",
            "future_data_used_for_signal": False,
            "never_seen_holdout": "PROTECTED",
            "consumes_holdout": False,
            "production_authorized": False,
            "overlapping_forward_windows": True,
            "round_trip_cost_bps": round_trip_cost_bps,
        },
        "parameters": contract["parameters"],
        "seed": seed,
        "metrics": metrics,
        "observation_count": len(observations),
        "eligible_date_count": len(dates),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--round-trip-cost-bps", type=float, default=0.0)
    args = parser.parse_args()
    try:
        result = run_validation(
            args.input_dir,
            args.config,
            args.output,
            seed=args.seed,
            round_trip_cost_bps=args.round_trip_cost_bps,
        )
    except ValidationError as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({
        "status": "COMPUTED",
        "schema": result["schema"],
        "observation_count": result["observation_count"],
        "eligible_date_count": result["eligible_date_count"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
