#!/usr/bin/env python3
"""Bounded, read-only local OpenD K_1M callback acceptance.

Uses the repository FutuK1MStreamingAdapter on an isolated quote context. It
does not touch an existing LiveFeed connection, send orders, or claim bar
closure. Session.ALL is used for US pre/post-market streaming.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any


DEFAULT_SYMBOLS = ("US.QQQ", "US.AMD")
MAX_SYMBOLS = 4
MIN_SAMPLE_SECONDS = 60
MAX_SAMPLE_SECONDS = 600
MIN_QUOTA_HEADROOM = 2


def _prepare_sdk_log_root() -> str:
    """Keep SDK diagnostic logs in a task-owned temp directory on Windows."""
    root = Path(tempfile.gettempdir()) / "stock-razor-futu-logs"
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.environ["APPDATA"] = str(root)
    return str(root)


def _valid_ohlcv(payload: dict[str, Any]) -> bool:
    values = [payload.get(name) for name in ("open", "high", "low", "close", "volume")]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in values
    ):
        return False
    open_, high, low, close, volume = values
    return (
        min(open_, high, low, close) > 0
        and volume >= 0
        and high >= max(open_, close, low) - 1e-5
        and low <= min(open_, close, high) + 1e-5
    )


def _run(symbols: tuple[str, ...], sample_seconds: int, host: str, port: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": "stock_razor_local_opend_k1m_realtime_acceptance_v1",
        "source": "Local moomoo OpenD / Futu OpenAPI",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_symbols": list(symbols),
        "session_mode": "ALL",
        "sample_seconds": sample_seconds,
        "status": "BLOCKED",
        "callback_state": "NOT_OBSERVED",
        "ohlcv_quality": "NOT_VERIFIED",
        "adapter_diagnostics": {},
        "bar_closure": "UNPROVEN",
        "timestamp_age_qualification": "NOT_COMPUTED_TIMEKEY_CONVENTION_UNPROVEN",
        "production_subscription_mutations": 0,
        "trade_execution": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

    _prepare_sdk_log_root()
    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)
    import futu as ft

    from data_provider.futu_k1m_streaming_adapter import FutuK1MStreamingAdapter
    from data_provider.live_feed_types import ProviderEventKind, SemanticStreamKey

    result["sdk_version"] = getattr(ft, "__version__", "unknown")
    events: list[Any] = []
    events_lock = threading.Lock()
    context = None
    adapter = None

    try:
        context = ft.OpenQuoteContext(host=host, port=port)
        global_ret, _ = context.get_global_state()
        quota_ret, quota = context.query_subscription(is_all_conn=True)
        own_ret, own = context.query_subscription(is_all_conn=False)
        own_used = own.get("own_used") if isinstance(own, dict) else None
        remaining = quota.get("remain") if isinstance(quota, dict) else None
        result["preflight"] = {
            "connection_ok": global_ret == ft.RET_OK and quota_ret == ft.RET_OK and own_ret == ft.RET_OK,
            "total_used": quota.get("total_used") if isinstance(quota, dict) else None,
            "remaining": remaining,
            "own_used": own_used,
        }
        if (
            result["preflight"]["connection_ok"] is not True
            or own_used != 0
            or type(remaining) is not int
            or remaining < MIN_QUOTA_HEADROOM
        ):
            result["reason"] = "PREFLIGHT_CONNECTION_OWNERSHIP_OR_QUOTA_BLOCKED"
            return result

        market_ret, market_state = context.get_market_state(list(symbols))
        result["market_state"] = (
            market_state.to_dict(orient="records")
            if market_ret == ft.RET_OK and hasattr(market_state, "to_dict")
            else "UNAVAILABLE"
        )
        keys = tuple(
            SemanticStreamKey("futu", "us", symbol, "K_1M", "1m", session_mode="ALL")
            for symbol in symbols
        )

        def collect(event: Any) -> None:
            with events_lock:
                events.append(event)

        adapter = FutuK1MStreamingAdapter(
            context,
            ft,
            runtime_instance_id="local-opend-k1m-acceptance",
            controller_generation=lambda: 1,
        )
        adapter.register_event_sink(collect)
        adapter.start()
        adapter.subscribe_streams(keys)
        readback = adapter.inspect_current_connection_subscriptions(keys)
        result["subscription_readback"] = {
            field: readback.get(field)
            for field in (
                "status", "requested_count", "matched_count", "missing_symbols",
                "total_used", "own_used", "remaining", "session_mode_evidence",
                "realtime_qualification",
            )
        }
        started = time.monotonic()
        time.sleep(sample_seconds)
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        adapter.stop()

        with events_lock:
            captured = list(events)
        rows = []
        for event in captured:
            if event.event_kind != ProviderEventKind.DATA:
                continue
            payload = dict(event.payload)
            rows.append({
                "symbol": event.semantic_stream_key.symbol,
                "time_key": event.provider_timestamp_raw,
                "received_at_utc": event.observed_at_utc.isoformat(),
                "open": payload.get("open"),
                "high": payload.get("high"),
                "low": payload.get("low"),
                "close": payload.get("close"),
                "volume": payload.get("volume"),
                "ohlcv_valid": _valid_ohlcv(payload),
                "bar_closure": event.diagnostic_fields.get("bar_closure", "UNPROVEN"),
            })

        by_symbol = {
            symbol: [row for row in rows if row["symbol"] == symbol]
            for symbol in symbols
        }
        all_rows_valid = bool(rows) and all(row["ohlcv_valid"] for row in rows)
        all_symbols_observed = all(by_symbol[symbol] for symbol in symbols)
        result.update({
            "callback_state": "OBSERVED" if rows else "NO_DATA_CALLBACK",
            "data_event_count": len(rows),
            "valid_ohlcv_event_count": sum(row["ohlcv_valid"] for row in rows),
            "ohlcv_quality": "PASS" if all_rows_valid else "BLOCKED_OR_NO_ROWS",
            "symbols_with_callbacks": sorted(symbol for symbol, values in by_symbol.items() if values),
            "unique_time_keys_by_symbol": {
                symbol: len({row["time_key"] for row in values if row["time_key"]})
                for symbol, values in by_symbol.items()
            },
            "first_last_by_symbol": {
                symbol: {
                    "first": values[0] if values else None,
                    "last": values[-1] if values else None,
                    "callback_rows": len(values),
                }
                for symbol, values in by_symbol.items()
            },
            "adapter_diagnostics": adapter.diagnostics(),
            "status": "PASS_CALLBACK_AND_OHLCV" if all_rows_valid and all_symbols_observed else "BLOCKED",
        })
        return result
    except Exception as exc:
        result["reason"] = "EXCEPTION_" + type(exc).__name__
        return result
    finally:
        if adapter is not None:
            try:
                adapter.stop()
            except Exception:
                pass
        if context is not None:
            try:
                context.close()
                result["temporary_context_closed"] = True
            except Exception:
                result["temporary_context_closed"] = False
        result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--sample-seconds", type=int, default=65)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11111)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    symbols = tuple(dict.fromkeys(str(value).strip().upper() for value in args.symbols))
    if (
        not symbols
        or len(symbols) > MAX_SYMBOLS
        or any(not symbol.startswith("US.") for symbol in symbols)
        or not MIN_SAMPLE_SECONDS <= args.sample_seconds <= MAX_SAMPLE_SECONDS
        or not 1 <= args.port <= 65535
        or not args.host
    ):
        parser.error("invalid symbols, sample duration, host, or port")

    result = _run(symbols, args.sample_seconds, args.host, args.port)
    rendered = json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result.get("status") == "PASS_CALLBACK_AND_OHLCV" else 1


if __name__ == "__main__":
    raise SystemExit(main())

