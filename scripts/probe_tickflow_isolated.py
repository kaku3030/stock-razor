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
import os
import re
import time
from typing import Any, Callable

SAFE_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
PERIODS = ("1m", "5m", "15m", "30m", "60m")
DEFAULT_SYMBOLS = ("159611.SZ", "518880.SH", "512730.SH")
MAX_SYMBOLS = 5


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


def _row_count(value: Any) -> int | None:
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, dict):
        # Official SDK may return a keyed mapping. The shape is not silently
        # assumed to represent a specific count or data-qualification status.
        return None
    return None


@contextmanager
def _hide_provider_output():
    """Suppress SDK notices/logs (possibly non-ASCII or carrying data/key)."""
    with open(os.devnull, "w", encoding="utf-8", errors="replace") as sink:
        with redirect_stdout(sink), redirect_stderr(sink):
            yield


def _operation(name: str, call: Callable[[], Any]) -> dict:
    started = time.perf_counter()
    try:
        with _hide_provider_output():
            result = call()
        return {
            "name": name,
            "operation": "COMPLETED",
            "elapsed_ms": _elapsed_ms(started),
            "row_count": _row_count(result),
            "schema_qualified": False,
        }
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
    """Best-effort bounded WS smoke. Callback errors never print payloads."""
    if not 0 < seconds <= 15:
        raise ValueError("WebSocket probe duration must be (0,15] seconds")
    counts = {"quote_callbacks": 0, "quote_events": 0, "error_callbacks": 0}
    stream = client.stream
    started = time.perf_counter()

    @stream.on_quotes
    def on_quotes(quotes: Any) -> None:
        counts["quote_callbacks"] += 1
        if isinstance(quotes, (list, tuple)):
            counts["quote_events"] += len(quotes)

    @stream.on_error
    def on_error(message: Any) -> None:
        counts["error_callbacks"] += 1

    state = "FAILED"
    reason = None
    try:
        with _hide_provider_output():
            stream.subscribe("quotes", list(symbols))
            stream.connect(block=False)
            time.sleep(seconds)
        state = "OBSERVED" if counts["quote_events"] else "NO_EVENTS_OBSERVED"
    except Exception as exc:
        reason = type(exc).__name__
    finally:
        try:
            with _hide_provider_output():
                stream.close()
        except Exception:
            state = "CLOSE_FAILED"
    return {
        "name": "websocket_quote_smoke",
        "operation": state,
        "elapsed_ms": _elapsed_ms(started),
        **counts,
        "failure_class": reason,
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
) -> dict:
    """Requires explicit mode premium; never reads or returns the actual key."""
    if mode not in {"metadata", "free", "premium"}:
        raise ValueError("unsupported probe mode")
    if ws_seconds and mode != "premium":
        raise ValueError("WebSocket probe requires explicit premium mode")
    if not 0 <= ws_seconds <= 15:
        raise ValueError("invalid WebSocket duration")

    symbols = validate_symbols(list(symbols))
    credential_present = bool(os.environ.get("TICKFLOW_API_KEY")) if credential_present is None else credential_present
    result = {
        "schema": "stock_razor_tickflow_isolated_probe_v0_1",
        "observed_at_utc": _utc(),
        "mode": mode,
        "provider": "TICKFLOW_SDK",
        "location": "LOCAL_ISOLATE",
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
        result["operations"].append(
            _operation(
                "kline_" + period,
                lambda period=period: client.klines.get(symbols[0], period=period, count=3),
            )
        )
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
    parser.add_argument("--mode", choices=("metadata", "free", "premium"), default="metadata")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--ws-seconds", type=float, default=0)
    args = parser.parse_args()
    try:
        symbols = validate_symbols(args.symbols)
        version = importlib.metadata.version("tickflow")
        result = build_probe(mode=args.mode, symbols=symbols,
                             ws_seconds=args.ws_seconds,
                             sdk_version=version)
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
