#!/usr/bin/env python3
"""Opt-in TickFlow WS protocol evidence collector; no canonical writes or trades.

Connection, subscribed ACK, cached first sample and later updates are distinct.
Only fixed counters/enums leave this process. Never print frames, API keys, URLs
or exceptions. No live feed qualification or source promotion is performed.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ENDPOINT = "wss://api.tickflow.org/v1/ws/stream"
SAFE_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
MAX_SYMBOLS = 200
SUBSCRIBE_BATCH_SIZE = 5
# The first two are held ETFs; 518880.SH is observation-only.
HOLDINGS = ("159611.SZ", "159209.SZ", "518880.SH", "512730.SH", "159363.SZ")
KLINE_PERIODS = ("1m", "5m", "15m", "60m", "1d")
_KLINE_FINGERPRINT_FIELDS = (
    "timestamp", "open", "high", "low", "close", "volume", "amount",
)


def kline_fingerprints(data: Any) -> dict[str, str]:
    """Hash rows by BAR timestamp so new bars are not counted as revisions."""
    if not isinstance(data, dict) or any(
        not isinstance(data.get(field), (list, tuple))
        for field in _KLINE_FINGERPRINT_FIELDS
    ):
        raise ValueError("invalid TickFlow K-line shape")
    lengths = {len(data[field]) for field in _KLINE_FINGERPRINT_FIELDS}
    if len(lengths) != 1:
        raise ValueError("inconsistent TickFlow K-line columns")
    result = {}
    for index in range(lengths.pop()):
        stamp = str(data["timestamp"][index])
        encoded = json.dumps(
            [data[field][index] for field in _KLINE_FINGERPRINT_FIELDS],
            separators=(",", ":"), default=str,
        ).encode("utf-8")
        result[stamp] = hashlib.sha256(encoded).hexdigest()
    return result


def has_overlapping_kline_revision(previous: dict[str, str], current: dict[str, str]) -> bool:
    """Return true only when an already-seen bar changes across snapshots."""
    return any(previous[stamp] != current[stamp]
               for stamp in previous.keys() & current.keys())


class ProtocolEvidence:
    """Strict ACK-first observer; a timestamp advance is not proof of live SLO."""

    def __init__(self, symbols: tuple[str, ...]):
        if not symbols or len(symbols) > MAX_SYMBOLS or len(set(symbols)) != len(symbols):
            raise ValueError("invalid symbols")
        if not all(SAFE_SYMBOL.fullmatch(s) for s in symbols):
            raise ValueError("invalid symbols")
        self.symbols = frozenset(symbols)
        self.ack_verified = False
        self.ack_symbols: set[str] = set()
        self.partial_ack_allowed = False
        self.ack_messages = 0
        self.invalid_ack_messages = 0
        self.pre_ack_quote_frames = 0
        self.quote_frames = 0
        self.initial_snapshot_candidates = 0
        self.post_initial_update_candidates = 0
        self.duplicate_timestamp_count = 0
        self.out_of_order_timestamp_count = 0
        self.invalid_timestamp_count = 0
        self.unknown_symbol_count = 0
        self.protocol_error_frames = 0
        self.invalid_frames = 0
        self.window_status = "UNOBSERVED"
        self._latest: dict[str, int] = {}
        self._post_initial_lags: list[int] = []
        self.post_initial_future_timestamp_count = 0
        self.post_initial_lag_truncated = False
        self.reconnect_attempts = 0
        self.reconnect_successes = 0
        self.planned_rotations = 0
        self.kline_snapshots = 0
        self.kline_digest_changes = 0
        self.kline_read_errors = 0

    def consume(self, frame: Any, *, received_at_ms: int | None = None) -> None:
        if received_at_ms is None:
            received_at_ms = time.time_ns() // 1_000_000
        if type(received_at_ms) is not int or received_at_ms < 0:
            raise ValueError("invalid local receive clock")
        try:
            item = json.loads(frame) if isinstance(frame, (str, bytes)) else frame
        except (ValueError, UnicodeDecodeError, TypeError):
            self.invalid_frames += 1
            return
        if not isinstance(item, dict):
            self.invalid_frames += 1
            return
        kind = item.get("op")
        if kind == "subscribed":
            syms = item.get("symbols")
            total = item.get("total")
            exact_ack = (isinstance(syms, list)
                    and all(isinstance(s, str) for s in syms)
                    and len(syms) == len(self.symbols)
                    and set(syms) == self.symbols
                    and type(total) is int and total == len(self.symbols))
            partial_ack = (self.partial_ack_allowed and isinstance(syms, list)
                    and all(isinstance(s, str) for s in syms)
                    # The client may append subscriptions in bounded batches;
                    # accept only an exact subset and require the union to
                    # cover the complete requested scope before ACK is true.
                    and 1 <= len(syms) <= len(self.symbols)
                    and len(set(syms)) == len(syms)
                    and set(syms).issubset(self.symbols)
                    and type(total) is int
                    and total in (len(syms), len(self.ack_symbols | set(syms))))
            if item.get("channel") == "quotes" and (exact_ack or partial_ack):
                self.ack_messages += 1
                self.ack_symbols.update(syms)
                self.ack_verified = self.ack_symbols == self.symbols
            else:
                self.invalid_ack_messages += 1
        elif kind == "quotes":
            if not self.ack_verified:
                self.pre_ack_quote_frames += 1
                return
            rows = item.get("data")
            if not isinstance(rows, list):
                self.invalid_frames += 1
                return
            self.quote_frames += 1
            for row in rows:
                if not isinstance(row, dict):
                    self.invalid_frames += 1
                    continue
                symbol = row.get("symbol")
                if symbol not in self.symbols:
                    self.unknown_symbol_count += 1
                    continue
                stamp = row.get("timestamp")
                # Official WS protocol specifies UNIX milliseconds, not seconds.
                if (type(stamp) not in (int, float) or not math.isfinite(stamp)
                        or not 1_000_000_000_000 <= stamp < 10_000_000_000_000):
                    self.invalid_timestamp_count += 1
                    continue
                millis = int(stamp)
                previous = self._latest.get(symbol)
                if previous is None:
                    self.initial_snapshot_candidates += 1
                    self._latest[symbol] = millis
                elif millis > previous:
                    self.post_initial_update_candidates += 1
                    self._latest[symbol] = millis
                    lag_ms = received_at_ms - millis
                    if lag_ms < 0:
                        self.post_initial_future_timestamp_count += 1
                    if len(self._post_initial_lags) < 4096:
                        self._post_initial_lags.append(lag_ms)
                    else:
                        self.post_initial_lag_truncated = True
                elif millis == previous:
                    self.duplicate_timestamp_count += 1
                else:
                    self.out_of_order_timestamp_count += 1
        elif kind == "error":
            # Never include the server-controlled message text.
            self.protocol_error_frames += 1
        else:
            self.invalid_frames += 1

    def _lag_bucket(self) -> str:
        # This is local EC2 receive-minus-provider-event time, NOT exchange
        # delivery SLA proof. A bad clock, provider labeling, or truncation
        # must veto any inferred 'fresh' bucket.
        if not self._post_initial_lags or self.post_initial_lag_truncated:
            return "NOT_VERIFIED"
        if self.post_initial_future_timestamp_count:
            return "CLOCK_CONFLICT"
        values = sorted(self._post_initial_lags)
        p95 = values[math.ceil(len(values) * 0.95) - 1]
        if p95 <= 2000:
            return "UNDER_2S"
        if p95 <= 5000:
            return "TWO_TO_FIVE_S"
        if p95 <= 30000:
            return "FIVE_TO_THIRTY_S"
        return "OVER_THIRTY_S"

    def summary(self, *, ws_handshake: bool) -> dict[str, Any]:
        # A preceding ACK cannot overrule a subsequent server-level error.
        # PASS here means only the protocol exchange, NOT continuous quotes.
        protocol_acceptance = (
            "FAIL" if (
                self.protocol_error_frames or self.invalid_ack_messages
                or self.window_status == "TERMINATED_EARLY"
            )
            else "PASS" if ws_handshake and self.ack_verified
            else "NOT_VERIFIED"
        )
        return {
            "schema": "stock_razor_tickflow_ws_ack_evidence_v0_1",
            "protocol_acceptance": protocol_acceptance,
            "protocol_acceptance_scope": "ACK_ONLY_NOT_LIVE_QUALIFICATION",
            "bounded_window_status": self.window_status,
            "post_initial_progress_status": (
                "OBSERVED_NOT_QUALIFIED"
                if self.post_initial_update_candidates >= 2
                else "INSUFFICIENT"
            ),
            "ws_handshake": "PASS" if ws_handshake else "NOT_VERIFIED",
            "subscription_ack": "PASS" if self.ack_verified else "NOT_VERIFIED",
            "ack_messages": self.ack_messages,
            "invalid_ack_messages": self.invalid_ack_messages,
            "pre_ack_quote_frames": self.pre_ack_quote_frames,
            "quote_frames": self.quote_frames,
            "initial_snapshot_candidates": self.initial_snapshot_candidates,
            "post_initial_update_candidates": self.post_initial_update_candidates,
            "post_initial_lag_samples": len(self._post_initial_lags),
            "post_initial_p95_lag_bucket": self._lag_bucket(),
            "post_initial_future_timestamp_count": self.post_initial_future_timestamp_count,
            "post_initial_lag_truncated": self.post_initial_lag_truncated,
            "timestamp_lag_not_live_qualified": True,
            "duplicate_timestamp_count": self.duplicate_timestamp_count,
            "out_of_order_timestamp_count": self.out_of_order_timestamp_count,
            "invalid_timestamp_count": self.invalid_timestamp_count,
            "unknown_symbol_count": self.unknown_symbol_count,
            "protocol_error_frames": self.protocol_error_frames,
            "invalid_frames": self.invalid_frames,
            "reconnect_attempts": self.reconnect_attempts,
            "reconnect_successes": self.reconnect_successes,
            "planned_rotations": self.planned_rotations,
            "kline_snapshots": self.kline_snapshots,
            "kline_digest_changes": self.kline_digest_changes,
            "kline_read_errors": self.kline_read_errors,
            "post_initial_update_not_proven_live": True,
            "continuous_feed_qualified": False,
            "source_arbiter_admission": "BLOCKED",
            "radar_admission": "BLOCKED",
            "live_trade": False,
            "canonical_write": False,
            "order_execution": False,
        }


async def observe_socket(
    ws: Any, evidence: ProtocolEvidence, seconds: int, on_tick: Any = None,
) -> None:
    if type(seconds) is not int or not 1 <= seconds <= 16800:
        raise ValueError("unsupported bounded duration")
    evidence.partial_ack_allowed = True
    symbols = sorted(evidence.symbols)
    for offset in range(0, len(symbols), SUBSCRIBE_BATCH_SIZE):
        await ws.send(json.dumps({
            "op": "subscribe", "channel": "quotes",
            "symbols": symbols[offset:offset + SUBSCRIBE_BATCH_SIZE],
        }))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(
                1.0, max(0.001, deadline - time.monotonic())
            ))
        except asyncio.TimeoutError:
            if time.monotonic() >= deadline - 0.02:
                evidence.window_status = "COMPLETED"
                return
            if on_tick is not None:
                await on_tick()
            continue
        except (EOFError, ConnectionError):
            evidence.window_status = "TERMINATED_EARLY"
            return
        evidence.consume(raw)
        if on_tick is not None:
            await on_tick()
    evidence.window_status = "COMPLETED"


async def run_protocol_probe(symbols: tuple[str, ...], seconds: int, *, key: str) -> dict[str, Any]:
    evidence = ProtocolEvidence(symbols)
    if type(seconds) is not int or not 10 <= seconds <= 16800 or not key or not key.strip():
        raise ValueError("invalid probe parameters")
    try:
        import websockets
    except ImportError:
        result = evidence.summary(ws_handshake=False)
        result["failure_class"] = "REALTIME_TRANSPORT_MISSING"
        return result
    endpoint = ENDPOINT + "?api_key=" + quote(key, safe="")
    deadline = time.monotonic() + seconds
    backoff = 1
    handshake = False
    cn_tz = ZoneInfo("Asia/Shanghai")
    run_day = datetime.now(cn_tz).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    checkpoints = {
        "PRE_CLOSE": run_day.replace(hour=14, minute=55),
        "POST_CLOSE": run_day.replace(hour=15, minute=2),
        "POST_CLOSE_65M": run_day.replace(hour=16, minute=5),
        "POST_CLOSE_80M": run_day.replace(hour=16, minute=20),
    }
    completed_checkpoints: set[str] = set()
    bar_fingerprints: dict[tuple[str, str], dict[str, str]] = {}
    client = None

    def snapshot_batch(label: str) -> tuple[int, int, int]:
        from tickflow import TickFlow
        nonlocal client
        if client is None:
            client = TickFlow(api_key=key, timeout=8.0, max_retries=0)
        rows = changes = errors = 0
        for symbol in symbols:
            for period in KLINE_PERIODS:
                try:
                    data = client.klines.get(
                        symbol, period=period, count=20,
                        adjust="none", as_dataframe=False,
                    )
                    key_tuple = (symbol, period)
                    current = kline_fingerprints(data)
                    previous = bar_fingerprints.get(key_tuple, {})
                    if has_overlapping_kline_revision(previous, current):
                        changes += 1
                    bar_fingerprints[key_tuple] = current
                    rows += 1
                except Exception:
                    errors += 1
        return rows, changes, errors

    async def maybe_snapshot() -> None:
        now = datetime.now(cn_tz)
        for label, due in checkpoints.items():
            if label not in completed_checkpoints and now >= due:
                completed_checkpoints.add(label)
                rows, changes, errors = await asyncio.to_thread(snapshot_batch, label)
                evidence.kline_snapshots += rows
                evidence.kline_digest_changes += changes
                evidence.kline_read_errors += errors

    # Always anchor the bounded realtime window with the same 20x5 K-line
    # matrix. Intraday checkpoint labels are intentionally future-dated during
    # the morning, so checkpoint-only snapshots would otherwise report zero
    # K-line reads even when the provider is healthy.
    rows, changes, errors = await asyncio.to_thread(
        snapshot_batch, "WINDOW_START",
    )
    evidence.kline_snapshots += rows
    evidence.kline_digest_changes += changes
    evidence.kline_read_errors += errors
    while time.monotonic() < deadline:
        try:
            evidence.ack_verified = False
            evidence.ack_symbols.clear()
            async with websockets.connect(
                endpoint, ping_interval=20, ping_timeout=10, open_timeout=5,
                max_size=16 * 1024 * 1024, compression="deflate",
            ) as ws:
                if handshake:
                    evidence.reconnect_successes += 1
                handshake = True
                backoff = 1
                session_seconds = min(900, max(1, int(deadline - time.monotonic())))
                await observe_socket(ws, evidence, session_seconds, maybe_snapshot)
                if time.monotonic() < deadline:
                    evidence.reconnect_attempts += 1
                    if evidence.window_status == "COMPLETED":
                        evidence.planned_rotations += 1
                    else:
                        await asyncio.sleep(min(backoff, max(0, deadline - time.monotonic())))
                        backoff = min(30, backoff * 2)
        except Exception as exc:
            # Never use str/repr or log raw WebSocket exceptions: can contain key.
            status = getattr(exc, "status_code", None)
            response = getattr(exc, "response", None)
            if type(getattr(response, "status_code", None)) is int:
                status = response.status_code
            if status in (401, 403):
                evidence.window_status = "TERMINATED_EARLY"
                result = evidence.summary(ws_handshake=handshake)
                result["failure_class"] = "AUTH_DENIED"
                return result
            if time.monotonic() < deadline:
                evidence.window_status = "TERMINATED_EARLY"
                evidence.reconnect_attempts += 1
                await asyncio.sleep(min(backoff, max(0, deadline - time.monotonic())))
                backoff = min(30, backoff * 2)
    evidence.window_status = "COMPLETED"
    rows, changes, errors = await asyncio.to_thread(
        snapshot_batch, "WINDOW_END",
    )
    evidence.kline_snapshots += rows
    evidence.kline_digest_changes += changes
    evidence.kline_read_errors += errors
    result = evidence.summary(ws_handshake=handshake)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    return result


def main() -> int:
    env_path = os.getenv("ENV_FILE") or str(Path(__file__).resolve().parents[1] / ".env")
    load_dotenv(env_path, override=False)
    parser = argparse.ArgumentParser(description="Isolated, explicit quote WS ACK observer")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=list(HOLDINGS))
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    if (not args.execute
            or os.environ.get("TICKFLOW_WS_PROTOCOL_PROBE_OPT_IN") != "true"
            or os.environ.get("TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED") != "true"):
        print(json.dumps({
            "status": "BLOCKED", "reason": "EXPLICIT_NETWORK_OPT_IN_REQUIRED",
            "radar_admission": "BLOCKED", "live_trade": False,
        }))
        return 2
    try:
        result = asyncio.run(run_protocol_probe(
            tuple(args.symbols), args.seconds,
            key=os.environ.get("TICKFLOW_API_KEY", ""),
        ))
    except (ValueError, RuntimeError):
        result = {
            "status": "BLOCKED", "reason": "INVALID_PROBE_PARAMETERS",
            "radar_admission": "BLOCKED", "live_trade": False,
        }
    print(json.dumps(result, sort_keys=True))
    # CLI success is ONLY a bounded protocol-progress smoke, never source
    # qualification: independent freshness, continuity and parity still gate.
    return 0 if (
        result.get("protocol_acceptance") == "PASS"
        and result.get("bounded_window_status") == "COMPLETED"
        and result.get("post_initial_progress_status") == "OBSERVED_NOT_QUALIFIED"
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
