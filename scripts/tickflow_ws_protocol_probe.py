#!/usr/bin/env python3
"""Opt-in TickFlow WS protocol evidence collector; no canonical writes or trades.

Connection, subscribed ACK, cached first sample and later updates are distinct.
Only fixed counters/enums leave this process. Never print frames, API keys, URLs
or exceptions. No live feed qualification or source promotion is performed.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import math
import os
import re
import time
from typing import Any
from urllib.parse import quote

ENDPOINT = "wss://api.tickflow.org/v1/ws/stream"
SAFE_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
MAX_SYMBOLS = 5


class ProtocolEvidence:
    """Strict ACK-first observer; a timestamp advance is not proof of live SLO."""

    def __init__(self, symbols: tuple[str, ...]):
        if not symbols or len(symbols) > MAX_SYMBOLS or len(set(symbols)) != len(symbols):
            raise ValueError("invalid symbols")
        if not all(SAFE_SYMBOL.fullmatch(s) for s in symbols):
            raise ValueError("invalid symbols")
        self.symbols = frozenset(symbols)
        self.ack_verified = False
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
            if (item.get("channel") == "quotes" and isinstance(syms, list)
                    and all(isinstance(s, str) for s in syms)
                    # One isolated connection sends exactly one subscription.
                    # Extra/duplicate symbols or inaccurate counts are not proof
                    # that only the requested bounded scope was acknowledged.
                    and len(syms) == len(self.symbols)
                    and set(syms) == self.symbols
                    and type(total) is int and total == len(self.symbols)):
                self.ack_messages += 1
                self.ack_verified = True
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
            "post_initial_update_not_proven_live": True,
            "continuous_feed_qualified": False,
            "source_arbiter_admission": "BLOCKED",
            "radar_admission": "BLOCKED",
            "live_trade": False,
            "canonical_write": False,
            "order_execution": False,
        }


async def observe_socket(ws: Any, evidence: ProtocolEvidence, seconds: int) -> None:
    if seconds not in (10, 15, 30, 60):
        raise ValueError("unsupported bounded duration")
    await ws.send(json.dumps({
        "op": "subscribe", "channel": "quotes",
        "symbols": sorted(evidence.symbols),
    }))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(
                ws.recv(), timeout=max(0.001, deadline - time.monotonic())
            )
        except asyncio.TimeoutError:
            # Only the deadline-reached timeout constitutes a full window.
            evidence.window_status = (
                "COMPLETED" if time.monotonic() >= deadline - 0.02
                else "TERMINATED_EARLY"
            )
            return
        except (EOFError, ConnectionError):
            evidence.window_status = "TERMINATED_EARLY"
            return
        evidence.consume(raw)
    evidence.window_status = "COMPLETED"


async def run_protocol_probe(symbols: tuple[str, ...], seconds: int, *, key: str) -> dict[str, Any]:
    evidence = ProtocolEvidence(symbols)
    if seconds not in (10, 15, 30, 60) or not key or not key.strip():
        raise ValueError("invalid probe parameters")
    try:
        import websockets
    except ImportError:
        result = evidence.summary(ws_handshake=False)
        result["failure_class"] = "REALTIME_TRANSPORT_MISSING"
        return result
    endpoint = ENDPOINT + "?api_key=" + quote(key, safe="")
    try:
        # Exactly one attempt: 401/403 must not retry.
        async with websockets.connect(
            endpoint, ping_interval=20, ping_timeout=10, open_timeout=5,
            max_size=16 * 1024 * 1024, compression="deflate",
        ) as ws:
            await observe_socket(ws, evidence, seconds)
            return evidence.summary(ws_handshake=True)
    except Exception as exc:
        # Never use str/repr or log raw WebSocket exceptions: can contain key.
        result = evidence.summary(ws_handshake=False)
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if type(getattr(response, "status_code", None)) is int:
            status = response.status_code
        result["failure_class"] = (
            "AUTH_DENIED" if status in (401, 403)
            else "NETWORK_OR_PROTOCOL_UNVERIFIED"
        )
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated, explicit quote WS ACK observer")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--symbols", nargs="+", default=["159611.SZ", "518880.SH"])
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
