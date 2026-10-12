"""Synthetic-only TickFlow ACK protocol tests: no provider credentials or I/O."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.tickflow_ws_protocol_probe import (
    ProtocolEvidence, observe_socket, run_protocol_probe, main,
)

SYMS = ("159611.SZ", "518880.SH")


def test_ack_initial_snapshot_and_advanced_timestamp_do_not_auto_promote():
    e = ProtocolEvidence(SYMS)
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": 1776754800000}]})
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2})
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": 1776754800000,
                                        "token": "DO_NOT_LEAK"}]})
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": 1776754801000,
                                        "last_price": 999}]})
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": 1776754801000}]})
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": 1776754799000}]})
    result = e.summary(ws_handshake=True)
    assert result["subscription_ack"] == "PASS"
    assert result["pre_ack_quote_frames"] == 1
    assert result["initial_snapshot_candidates"] == 1
    assert result["post_initial_update_candidates"] == 1
    assert result["duplicate_timestamp_count"] == 1
    assert result["out_of_order_timestamp_count"] == 1
    assert result["continuous_feed_qualified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert "DO_NOT_LEAK" not in json.dumps(result)
    assert "999" not in json.dumps(result)


def test_wrong_channel_missing_symbol_bad_boolean_total_never_ack():
    e = ProtocolEvidence(SYMS)
    e.consume({"op": "subscribed", "channel": "depth", "symbols": list(SYMS), "total": 2})
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": [SYMS[0]], "total": 1})
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": True})
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": 1776754800000}]})
    assert e.summary(ws_handshake=True)["subscription_ack"] == "NOT_VERIFIED"
    assert e.invalid_ack_messages == 3
    assert e.pre_ack_quote_frames == 1
    assert e.initial_snapshot_candidates == 0


def test_bad_timestamp_unknown_symbol_and_server_error_stay_sanitized():
    e = ProtocolEvidence(SYMS)
    e.consume("{invalid-json-secret-body")
    e.consume({"op": "error", "message": "api_key=DO_NOT_LEAK"})
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2})
    e.consume({"op": "quotes", "data": [
        {"symbol": SYMS[0], "timestamp": True},
        {"symbol": SYMS[0], "timestamp": 1776754800},
        {"symbol": SYMS[0], "timestamp": float("nan")},
        {"symbol": "999999.SZ", "timestamp": 1776754800000},
        {"symbol": SYMS[1], "timestamp": 1776754800000},
    ]})
    summary = e.summary(ws_handshake=True)
    assert summary["invalid_timestamp_count"] == 3
    assert summary["unknown_symbol_count"] == 1
    assert summary["protocol_error_frames"] == 1
    assert summary["invalid_frames"] == 1
    assert "DO_NOT_LEAK" not in json.dumps(summary)


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.frames = [
            json.dumps({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2}),
            json.dumps({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": 1776754800000}]}),
        ]

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        if self.frames:
            return self.frames.pop(0)
        raise EOFError("done")


def test_bounded_session_sends_only_quotes_and_closes_without_network():
    fake = FakeSocket()
    e = ProtocolEvidence(SYMS)
    asyncio.run(observe_socket(fake, e, 10))
    assert len(fake.sent) == 1
    assert json.loads(fake.sent[0]) == {
        "op": "subscribe", "channel": "quotes", "symbols": sorted(SYMS),
    }
    assert e.summary(ws_handshake=True)["subscription_ack"] == "PASS"


@pytest.mark.parametrize("values", [(), ("INVALID",), ("159611.SZ",) * 6, ("159611.SZ",) * 2])
def test_untrusted_symbols_fail_closed(values):
    with pytest.raises(ValueError):
        ProtocolEvidence(values)


def test_403_never_reconnects_or_leaks_exception_url(monkeypatch):
    class AuthReject(Exception):
        def __init__(self):
            super().__init__("wss://api.tickflow.org/v1/ws/stream?api_key=DO_NOT_LEAK")
            self.response = SimpleNamespace(status_code=403)

    class FakeWebsockets:
        calls = 0

        @classmethod
        def connect(cls, *args, **kwargs):
            cls.calls += 1

            class Conn:
                async def __aenter__(self):
                    raise AuthReject()

                async def __aexit__(self, *args):
                    pass

            return Conn()

    monkeypatch.setitem(sys.modules, "websockets", FakeWebsockets)
    result = asyncio.run(run_protocol_probe(SYMS, 10, key="DO_NOT_LEAK"))
    assert FakeWebsockets.calls == 1
    assert result["failure_class"] == "AUTH_DENIED"
    assert result["subscription_ack"] == "NOT_VERIFIED"
    assert "DO_NOT_LEAK" not in json.dumps(result)


def test_default_cli_fails_closed_without_network_optin(monkeypatch, capsys):
    monkeypatch.delenv("TICKFLOW_WS_PROTOCOL_PROBE_OPT_IN", raising=False)
    monkeypatch.setenv("TICKFLOW_API_KEY", "DO_NOT_LEAK")
    monkeypatch.setattr(sys, "argv", ["proto", "--execute", "--seconds", "10"])
    assert main() == 2
    output = capsys.readouterr().out
    assert "EXPLICIT_NETWORK_OPT_IN_REQUIRED" in output
    assert "DO_NOT_LEAK" not in output


def test_schema_and_invariant_not_a_production_admission():
    e = ProtocolEvidence(SYMS)
    assert e.summary(ws_handshake=True)["subscription_ack"] == "NOT_VERIFIED"
    assert e.summary(ws_handshake=True)["continuous_feed_qualified"] is False
    assert e.summary(ws_handshake=True)["canonical_write"] is False
    assert e.summary(ws_handshake=True)["order_execution"] is False
