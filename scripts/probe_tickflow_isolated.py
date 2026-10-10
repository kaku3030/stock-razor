#!/usr/bin/env python3
"""TickFlow isolated read-only capability probe; never writes canonical data.

NO production collector, Radar, source arbitration, notification or orders.
Use only official Python SDK. Do not print provider payloads or error messages.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
import re
import time
from typing import Any, Callable

SAFE_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
PERIODS = ("1m", "5m", "15m", "30m", "60m")
DEFAULT_SYMBOLS = ("159611.SZ", "518880.SH", "512730.SH")
MAX_SYMBOLS = 5
PREMIUM_AUTH_METHOD = "AWS_IAM_ROLE_WITH_SECRET_REFERENCE"
PREMIUM_ALLOWED_INTERFACES = (
    "quotes",
    "klines",
    "depth",
    "websocket_quotes",
)


def validate_symbols(values: list[str]) -> tuple[str, ...]:
    if not 1 <= len(values) <= MAX_SYMBOLS:
        raise ValueError("symbol count must be 1..5")
    normalized = []
    for item in values:
        value = item.strip().upper()
        if not SAFE_SYMBOL.fullmatch(value):
            raise ValueError("invalid CN security symbol")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * weight, 3)


def _row_count(value: Any) -> int | None:
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, dict):
        rows = _rows(value)
        return len(rows) if rows is not None else None
    return None


def _rows(value: Any) -> list[Any] | None:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        for key in ("data", "rows", "items", "klines", "candles"):
            candidate = value.get(key)
            if isinstance(candidate, (list, tuple)):
                return list(candidate)
        column_names = (
            "timestamp", "time", "datetime", "date", "open", "high", "low",
            "close", "volume", "amount", "open_interest", "prev_close",
        )
        columns = {
            name: list(value[name])
            for name in column_names
            if isinstance(value.get(name), (list, tuple))
        }
        if columns:
            row_count = max(len(column) for column in columns.values())
            return [
                {name: column[index] for name, column in columns.items() if index < len(column)}
                for index in range(row_count)
            ]
    return None


def _field(row: Any, names: tuple[str, ...]) -> Any:
    if not isinstance(row, dict):
        return None
    for name in names:
        if name in row:
            return row[name]
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _timestamp(value: Any) -> float | None:
    number = _number(value)
    if number is not None:
        return number / 1000 if number >= 10_000_000_000 else number
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _ohlcv_anomaly_diagnostics(
    numbers: dict[str, list[float | None]],
    numeric_fields: dict[str, bool],
    *,
    sample_count: int,
) -> dict[str, Any]:
    """Classify OHLCV failures without returning provider values."""
    reasons = {
        "HIGH_BELOW_OPEN_OR_CLOSE": 0,
        "LOW_ABOVE_OPEN_OR_CLOSE": 0,
        "NEGATIVE_VOLUME": 0,
        "TOLERANCE_PRECISION": 0,
        "COUNT_ONLY": 0,
    }
    required = ("open", "high", "low", "close", "volume")
    if sample_count == 0 or not all(numeric_fields.get(name, False) for name in required):
        reasons["COUNT_ONLY"] = sample_count
        return {
            "status": "NOT_VERIFIED",
            "reasons": [name for name, count in reasons.items() if count],
            "counts": reasons,
        }

    for open_, high, low, close, volume in zip(
        numbers["open"], numbers["high"], numbers["low"],
        numbers["close"], numbers["volume"],
    ):
        if volume is not None and volume < 0:
            reasons["NEGATIVE_VOLUME"] += 1
        if None in (open_, high, low, close):
            reasons["COUNT_ONLY"] += 1
            continue
        scale = max(abs(open_), abs(high), abs(low), abs(close), 1.0)
        tolerance = scale * 1e-12
        high_gap = max(open_, close) - high
        low_gap = low - min(open_, close)
        for gap, reason in (
            (high_gap, "HIGH_BELOW_OPEN_OR_CLOSE"),
            (low_gap, "LOW_ABOVE_OPEN_OR_CLOSE"),
        ):
            if gap <= 0:
                continue
            if gap <= tolerance:
                reasons["TOLERANCE_PRECISION"] += 1
            else:
                reasons[reason] += 1

    failed = any(
        reasons[name]
        for name in (
            "HIGH_BELOW_OPEN_OR_CLOSE",
            "LOW_ABOVE_OPEN_OR_CLOSE",
            "NEGATIVE_VOLUME",
        )
    )
    return {
        "status": "FAILED" if failed else "PASS",
        "reasons": [name for name, count in reasons.items() if count],
        "counts": reasons,
    }


def _kline_summary(value: Any, *, period: str) -> dict[str, Any]:
    """Return only field-level evidence; never return bar values or payloads."""
    rows = _rows(value)
    fields = {
        "timestamp": ("timestamp", "time", "datetime", "date"),
        "open": ("open", "open_price"),
        "high": ("high", "high_price"),
        "low": ("low", "low_price"),
        "close": ("close", "close_price"),
        "volume": ("volume", "vol"),
        "amount": ("amount", "turnover"),
    }
    if rows is None:
        return {
            "sample_count": None,
            "field_presence": {name: False for name in fields},
            "numeric_fields": {name: "NOT_VERIFIED" for name in fields if name != "timestamp"},
            "timestamp_monotonicity": "NOT_VERIFIED",
            "timestamp_first": None,
            "timestamp_last": None,
            "ohlcv_range_valid": "NOT_VERIFIED",
            "ohlcv_anomaly_diagnostics": {
                "status": "NOT_VERIFIED",
                "reasons": ["COUNT_ONLY"],
                "counts": {
                    "HIGH_BELOW_OPEN_OR_CLOSE": 0,
                    "LOW_ABOVE_OPEN_OR_CLOSE": 0,
                    "NEGATIVE_VOLUME": 0,
                    "TOLERANCE_PRECISION": 0,
                    "COUNT_ONLY": 0,
                },
            },
            "closure": "NOT_VERIFIED",
            "freshness": "NOT_VERIFIED",
            "entitlement_evidence": "UNKNOWN",
            "period": period,
        }

    timestamps = [_timestamp(_field(row, fields["timestamp"])) for row in rows]
    numbers = {
        name: [_number(_field(row, aliases)) for row in rows]
        for name, aliases in fields.items()
        if name != "timestamp"
    }
    numeric_fields = {
        name: all(item is not None for item in values) if values else False
        for name, values in numbers.items()
    }
    valid_timestamps = [item for item in timestamps if item is not None]
    if len(valid_timestamps) == len(timestamps) and valid_timestamps:
        if all(left < right for left, right in zip(valid_timestamps, valid_timestamps[1:])):
            monotonicity = "STRICTLY_INCREASING"
        elif all(left <= right for left, right in zip(valid_timestamps, valid_timestamps[1:])):
            monotonicity = "NON_DECREASING"
        else:
            monotonicity = "NOT_MONOTONIC"
    else:
        monotonicity = "NOT_VERIFIED"

    ohlcv_range_valid: bool | str = "NOT_VERIFIED"
    if all(numeric_fields[name] for name in ("open", "high", "low", "close", "volume")):
        ohlcv_range_valid = all(
            high + (max(abs(open_), abs(high), abs(low), abs(close), 1.0) * 1e-12) >= max(open_, close)
            and low - (max(abs(open_), abs(high), abs(low), abs(close), 1.0) * 1e-12) <= min(open_, close)
            and volume >= 0
            for open_, high, low, close, volume in zip(
                numbers["open"], numbers["high"], numbers["low"],
                numbers["close"], numbers["volume"],
            )
        )
    diagnostics = _ohlcv_anomaly_diagnostics(
        numbers, numeric_fields, sample_count=len(rows)
    )

    age_ms = None
    if valid_timestamps:
        age_ms = round(max(0.0, time.time() - valid_timestamps[-1]) * 1000, 3)
    return {
        "sample_count": len(rows),
        "field_presence": {
            name: any(_field(row, aliases) is not None for row in rows)
            for name, aliases in fields.items()
        },
        "numeric_fields": numeric_fields,
        "timestamp_monotonicity": monotonicity,
        "timestamp_first": valid_timestamps[0] if valid_timestamps else None,
        "timestamp_last": valid_timestamps[-1] if valid_timestamps else None,
        "latest_timestamp_age_ms": age_ms,
        "ohlcv_range_valid": ohlcv_range_valid,
        "ohlcv_anomaly_diagnostics": diagnostics,
        "closure": "NOT_VERIFIED",
        "freshness": "NOT_VERIFIED",
        "entitlement_evidence": "UNKNOWN",
        "period": period,
    }


def evaluate_premium_execution_gate(
    *,
    auth_method: str,
    requested_interfaces: tuple[str, ...],
    credential_reference_available: bool | None,
    iam_read_permission: str,
    provider_entitlement: str,
    provider_region_authorized: str,
    concurrent_use_authorized: str,
    websocket_authorized: str,
    rate_limit_authorized: str,
    data_qualification: str,
) -> dict[str, Any]:
    """Evaluate the Premium contract without reading a credential or calling SDK."""
    if auth_method != PREMIUM_AUTH_METHOD:
        raise ValueError("unsupported Premium authentication method")
    requested = tuple(dict.fromkeys(requested_interfaces))
    if not requested or any(item not in PREMIUM_ALLOWED_INTERFACES for item in requested):
        raise ValueError("Premium interface is not allowed")

    gates = {
        "credential_reference": (
            "PASS" if credential_reference_available is True
            else "FAIL" if credential_reference_available is False
            else "UNKNOWN"
        ),
        "iam_read_permission": iam_read_permission,
        "provider_entitlement": provider_entitlement,
        "provider_region_authorized": provider_region_authorized,
        "concurrent_use_authorized": concurrent_use_authorized,
        "websocket_authorized": websocket_authorized,
        "rate_limit_authorized": rate_limit_authorized,
        "data_qualification": data_qualification,
    }
    if any(value not in {"PASS", "FAIL", "UNKNOWN"} for value in gates.values()):
        raise ValueError("Premium gate values must be PASS, FAIL, or UNKNOWN")

    blocked_reasons = [
        f"{name.upper()}_{value}"
        for name, value in gates.items()
        if value != "PASS"
    ]
    return {
        "schema": "stock_razor_tickflow_aws_premium_contract_v0_1",
        "auth_method": auth_method,
        "requested_interfaces": list(requested),
        "allowed_interfaces": list(PREMIUM_ALLOWED_INTERFACES),
        "gates": gates,
        "premium_execution": "ALLOWED" if not blocked_reasons else "BLOCKED",
        "blocked_reasons": blocked_reasons,
        "execution_scope": "READ_ONLY_PROBE_ONLY",
        "network_execution": False,
        "canonical_write": False,
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


@contextmanager
def _hide_provider_output():
    """Suppress SDK notices/logs (possibly non-ASCII or carrying data/key)."""
    with open(os.devnull, "w", encoding="utf-8", errors="replace") as sink:
        with redirect_stdout(sink), redirect_stderr(sink):
            yield


def _operation(name: str, call: Callable[[], Any], *, summarize: Callable[[Any], dict] | None = None) -> dict:
    started = time.perf_counter()
    try:
        with _hide_provider_output():
            result = call()
        operation = {
            "name": name,
            "operation": "COMPLETED",
            "elapsed_ms": _elapsed_ms(started),
            "row_count": _row_count(result),
            "schema_qualified": False,
        }
        if summarize is not None:
            operation["summary"] = summarize(result)
        return operation
    except Exception as exc:
        # Exception messages may include URL, provider responses or credentials.
        return {
            "name": name,
            "operation": "FAILED",
            "elapsed_ms": _elapsed_ms(started),
            "failure_class": type(exc).__name__,
            "schema_qualified": False,
        }


def _skip(name: str, reason: str) -> dict:
    return {"name": name, "operation": "SKIPPED", "reason": reason}


def _stream_probe(client: Any, symbols: tuple[str, ...], seconds: float) -> dict:
    """Bounded WebSocket observation, NOT a subscription or live-feed qualifier.

    The official sync SDK exposes quote/error callbacks but not the server's
    subscribed acknowledgement. The first sample for every symbol may be a
    cached snapshot; even later samples are only update *candidates*.
    Never interpret the initial snapshot or any unqualified age as E2E lag.
    """
    if not 0 < seconds <= 15:
        raise ValueError("WebSocket probe duration must be (0,15] seconds")
    counts = {
        "quote_callbacks": 0,
        "quote_events": 0,
        "unique_quote_samples": 0,
        "initial_snapshot_candidates": 0,
        "post_initial_update_candidates": 0,
        "duplicate_timestamp_events": 0,
        "out_of_order_timestamp_events": 0,
        "unrequested_symbol_events": 0,
        "invalid_timestamp_events": 0,
        "error_callbacks": 0,
    }
    allowed_symbols = set(symbols)
    last_provider_timestamp_ms: dict[str, float] = {}
    initial_candidate_deltas_ms: list[float] = []
    post_initial_candidate_deltas_ms: list[float] = []
    stream = client.stream
    started = time.perf_counter()

    @stream.on_quotes
    def on_quotes(quotes: Any) -> None:
        counts["quote_callbacks"] += 1
        if not isinstance(quotes, (list, tuple)):
            return
        counts["quote_events"] += len(quotes)
        arrival_ms = time.time() * 1000
        for quote in quotes:
            if not isinstance(quote, dict):
                counts["invalid_timestamp_events"] += 1
                continue
            symbol = quote.get("symbol")
            if not isinstance(symbol, str) or symbol not in allowed_symbols:
                counts["unrequested_symbol_events"] += 1
                continue
            raw_timestamp = quote.get("timestamp")
            if (
                isinstance(raw_timestamp, bool)
                or not isinstance(raw_timestamp, (int, float))
                or not math.isfinite(raw_timestamp)
                or raw_timestamp <= 0
            ):
                counts["invalid_timestamp_events"] += 1
                continue
            provider_ms = float(raw_timestamp)
            if provider_ms < 10_000_000_000:
                provider_ms *= 1000
            previous = last_provider_timestamp_ms.get(symbol)
            if previous is None:
                # This can be an initial cached quote. Never label it live.
                counts["initial_snapshot_candidates"] += 1
                initial_candidate_deltas_ms.append(arrival_ms - provider_ms)
                last_provider_timestamp_ms[symbol] = provider_ms
                counts["unique_quote_samples"] += 1
            elif provider_ms == previous:
                counts["duplicate_timestamp_events"] += 1
            elif provider_ms < previous:
                counts["out_of_order_timestamp_events"] += 1
            else:
                # Not enough to prove that it was produced after subscription.
                counts["post_initial_update_candidates"] += 1
                post_initial_candidate_deltas_ms.append(arrival_ms - provider_ms)
                last_provider_timestamp_ms[symbol] = provider_ms
                counts["unique_quote_samples"] += 1

    @stream.on_error
    def on_error(message: Any) -> None:
        counts["error_callbacks"] += 1

    state = "FAILED"
    reason = None
    connection_call = "NOT_VERIFIED"
    subscription_call = "NOT_VERIFIED"
    try:
        with _hide_provider_output():
            stream.subscribe("quotes", list(symbols))
            subscription_call = "PASS"
            stream.connect(block=False)
            connection_call = "PASS"
            time.sleep(seconds)
        state = "OBSERVED" if counts["quote_events"] else "NO_EVENTS_OBSERVED"
    except Exception as exc:
        reason = type(exc).__name__
        if subscription_call == "NOT_VERIFIED":
            subscription_call = "FAIL"
        elif connection_call == "NOT_VERIFIED":
            connection_call = "FAIL"
    finally:
        try:
            with _hide_provider_output():
                stream.close()
        except Exception:
            state = "CLOSE_FAILED"

    def metrics(samples: list[float]) -> dict:
        return {
            "count": len(samples),
            "p50": _percentile(samples, 50),
            "p95": _percentile(samples, 95),
            "p99": _percentile(samples, 99),
        }

    connection_state = "FAIL" if connection_call == "FAIL" else "UNKNOWN"
    subscription_state = (
        "FAIL" if subscription_call == "FAIL" else "UNKNOWN"
    )
    event_state = "PASS" if counts["quote_events"] else "UNKNOWN"

    return {
        "name": "websocket_quote_smoke",
        "operation": state,
        "elapsed_ms": _elapsed_ms(started),
        **counts,
        "failure_class": reason,
        "connection_call": connection_call,
        "connection_state": connection_state,
        "connection_method": "stream.connect(block=False)",
        "subscription_call": subscription_call,
        "subscription_state": subscription_state,
        "subscription_method": "stream.subscribe(channel='quotes', symbols=<validated>)",
        "event_state": event_state,
        "first_per_symbol_cache_candidate_age_ms": metrics(initial_candidate_deltas_ms),
        # Backwards-compatible key but now excludes initial cached snapshots.
        "arrival_minus_provider_timestamp_ms": metrics(post_initial_candidate_deltas_ms),
        "lag_scope": "POST_INITIAL_CANDIDATES_ONLY_NOT_VERIFIED_LIVE",
        "subscribed_ack_evidence": "NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK",
        "snapshot_vs_live_evidence": "NOT_VERIFIED",
        "ping_pong_evidence": "NOT_VERIFIED",
        "reconnect_resubscribe_evidence": "NOT_VERIFIED",
        "sample_latency_qualification": "NOT_VERIFIED",
        "clock_offset_qualification": "NOT_VERIFIED",
        "continuous_feed_qualified": False,
        "stale_drop_reconnect_qualified": False,
    }

def build_probe(
    *,
    mode: str,
    symbols: tuple[str, ...],
    ws_seconds: float = 0,
    client_factory: Any = None,
    sdk_version: str | None = None,
    credential_present: bool | None = None,
    location: str = "LOCAL_ISOLATE",
) -> dict:
    """Requires explicit mode premium; never reads or returns the actual key."""
    if mode not in {"metadata", "free", "premium", "premium-contract"}:
        raise ValueError("unsupported probe mode")
    if ws_seconds and mode != "premium":
        raise ValueError("WebSocket probe requires explicit premium mode")
    if not 0 <= ws_seconds <= 60:
        raise ValueError("invalid WebSocket duration")

    symbols = validate_symbols(list(symbols))
    if location not in {"LOCAL_ISOLATE", "AWS_TOKYO_SSM_ISOLATE"}:
        raise ValueError("unsupported location")
    credential_present = bool(os.environ.get("TICKFLOW_API_KEY")) if credential_present is None else credential_present
    result = {
        "schema": "stock_razor_tickflow_isolated_probe_v0_1",
        "observed_at_utc": _utc(),
        "mode": mode,
        "provider": "TICKFLOW_SDK",
        "location": location,
        "sdk_version": sdk_version,
        "api_key_present": credential_present,
        "symbols": list(symbols),
        "operations": [],
        "cloud_independence": "NOT_VERIFIED",
        "real_market_slo": "NOT_VERIFIED",
        "schema_units_timezone_adjustment": "NOT_VERIFIED",
        "source_cross_check": "NOT_VERIFIED",
        "source_arbiter_admission": "BLOCKED",
        "data_qualification": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "can_confirm_signal": False,
        "live_trade": False,
        "canonical_write": False,
        "order_execution": False,
    }
    if mode == "premium-contract":
        contract = evaluate_premium_execution_gate(
            auth_method=PREMIUM_AUTH_METHOD,
            requested_interfaces=PREMIUM_ALLOWED_INTERFACES,
            credential_reference_available=False,
            iam_read_permission="UNKNOWN",
            provider_entitlement="UNKNOWN",
            provider_region_authorized="UNKNOWN",
            concurrent_use_authorized="UNKNOWN",
            websocket_authorized="UNKNOWN",
            rate_limit_authorized="UNKNOWN",
            data_qualification="UNKNOWN",
        )
        result.update({
            "premium_contract": contract,
            "premium_execution": contract["premium_execution"],
        })
        result["operations"].append({
            "name": "premium_execution_gate",
            "operation": "BLOCKED",
            "reason_codes": contract["blocked_reasons"],
        })
        return result
    is_official_sdk = client_factory is None
    if client_factory is None:
        try:
            with _hide_provider_output():
                from tickflow import TickFlow
        except Exception as exc:
            # Includes Windows ZoneInfoNotFoundError when tzdata is absent.
            # Never dump arbitrary SDK or package-manager exception bodies.
            result["operations"].append({
                "name": "sdk_import",
                "operation": "FAILED",
                "failure_class": type(exc).__name__,
            })
            return result
        client_factory = TickFlow
    result["operations"].append({
        "name": "sdk_import",
        "operation": "COMPLETED",
    })
    if mode == "metadata":
        return result
    if mode == "premium" and not credential_present:
        result["operations"].append(_skip("premium_probe", "NO_API_KEY"))
        return result

    try:
        with _hide_provider_output():
            if mode == "free":
                client = (
                    client_factory.free(timeout=8.0, max_retries=0)
                    if is_official_sdk else client_factory.free()
                )
            else:
                client = (
                    client_factory(timeout=8.0, max_retries=0)
                    if is_official_sdk else client_factory()
                )  # SDK reads TICKFLOW_API_KEY from environment
    except Exception as exc:
        result["operations"].append({
            "name": "client_initialize",
            "operation": "FAILED",
            "failure_class": type(exc).__name__,
        })
        return result
    if mode == "free":
        result["operations"].append(
            _operation(
                "free_daily_kline",
                lambda: client.klines.get(symbols[0], period="1d", count=5),
            )
        )
        return result

    result["operations"].append(
        _operation("realtime_quote", lambda: client.quotes.get(symbols=list(symbols)))
    )
    for period in PERIODS:
        kline_symbols = symbols if period in {"15m", "60m"} else (symbols[0],)
        for symbol in kline_symbols:
            result["operations"].append(
                _operation(
                    "kline_" + period,
                    lambda period=period, symbol=symbol: client.klines.get(
                        symbol, period=period, count=3
                    ),
                    summarize=(
                        lambda value, period=period: _kline_summary(value, period=period)
                    ) if period in {"15m", "60m"} else None,
                )
            )
            if period in {"15m", "60m"}:
                result["operations"][-1]["symbol"] = symbol
    result["operations"].append(
        _operation("five_level_depth", lambda: client.depth.get(symbols[0]))
    )
    if ws_seconds:
        result["operations"].append(_stream_probe(client, symbols, ws_seconds))
    else:
        result["operations"].append(_skip("websocket_quote_smoke", "NOT_REQUESTED"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("metadata", "free", "premium", "premium-contract"),
        default="metadata",
    )
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--ws-seconds", type=float, default=0)
    parser.add_argument("--location", choices=("LOCAL_ISOLATE", "AWS_TOKYO_SSM_ISOLATE"), default="LOCAL_ISOLATE")
    args = parser.parse_args()
    try:
        symbols = validate_symbols(args.symbols)
        version = (
            None if args.mode == "premium-contract"
            else importlib.metadata.version("tickflow")
        )
        result = build_probe(mode=args.mode, symbols=symbols,
                             ws_seconds=args.ws_seconds,
                             sdk_version=version, location=args.location)
    except (ValueError, importlib.metadata.PackageNotFoundError) as exc:
        # Avoid exception text; the failure class alone is enough.
        result = {
            "schema": "stock_razor_tickflow_isolated_probe_v0_1",
            "setup_state": "BLOCKED",
            "failure_class": type(exc).__name__,
            "radar_admission": "BLOCKED",
            "live_trade": False,
            "can_confirm_signal": False,
        }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("setup_state") != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
