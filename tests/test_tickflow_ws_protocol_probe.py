"""Synthetic-only TickFlow ACK protocol tests: no provider credentials or I/O."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.tickflow_ws_protocol_probe import (
    ProtocolEvidence, has_overlapping_kline_revision, kline_fingerprints,
    HOLDINGS, KLINE_PERIODS, observe_socket, run_protocol_probe, main,
)

SYMS = ("159611.SZ", "518880.SH")


def test_default_cloud_matrix_is_the_four_holdings_and_five_periods():
    assert HOLDINGS == ("159611.SZ", "159209.SZ", "518880.SH", "512730.SH", "159363.SZ")
    assert KLINE_PERIODS == ("1m", "5m", "15m", "60m", "1d")


def test_kline_fingerprint_compares_overlapping_bars_not_new_rows():
    first = {
        "timestamp": [1, 2], "open": [1.0, 2.0], "high": [1.1, 2.1],
        "low": [0.9, 1.9], "close": [1.0, 2.0], "volume": [10, 20],
        "amount": [100, 200],
    }
    later = {key: list(values) for key, values in first.items()}
    for key, value in {
        "timestamp": 3, "open": 3.0, "high": 3.1, "low": 2.9,
        "close": 3.0, "volume": 30, "amount": 300,
    }.items():
        later[key].append(value)
    first_fp = kline_fingerprints(first)
    assert not has_overlapping_kline_revision(first_fp, kline_fingerprints(later))
    later["close"][1] = 2.01
    assert has_overlapping_kline_revision(first_fp, kline_fingerprints(later))


def test_kline_fingerprint_rejects_inconsistent_column_lengths():
    data = {key: [1] for key in (
        "timestamp", "open", "high", "low", "close", "volume", "amount",
    )}
    data["close"].append(1.0)
    with pytest.raises(ValueError):
        kline_fingerprints(data)


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
    assert e.summary(ws_handshake=True)["bounded_window_status"] == "TERMINATED_EARLY"
    assert e.summary(ws_handshake=True)["protocol_acceptance"] == "FAIL"


def test_twenty_symbol_session_sends_four_bounded_subscriptions_and_unions_acks():
    symbols = tuple(f"{100000 + index:06d}.SZ" for index in range(20))

    class TwentySocket:
        def __init__(self):
            self.sent = []
            self.frames = [
                json.dumps({
                    "op": "subscribed", "channel": "quotes",
                    "symbols": list(sorted(symbols))[offset:offset + 5], "total": 5,
                }) for offset in range(0, 20, 5)
            ]

        async def send(self, message):
            self.sent.append(message)

        async def recv(self):
            if self.frames:
                return self.frames.pop(0)
            raise EOFError("done")

    fake = TwentySocket()
    evidence = ProtocolEvidence(symbols)
    asyncio.run(observe_socket(fake, evidence, 10))
    assert len(fake.sent) == 4
    assert evidence.summary(ws_handshake=True)["subscription_ack"] == "PASS"


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


def test_provider_error_after_valid_ack_vetoes_protocol_acceptance():
    e = ProtocolEvidence(SYMS)
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2})
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": 1776754800000}]})
    e.consume({"op": "error", "message": "no permission: DO_NOT_LEAK"})
    result = e.summary(ws_handshake=True)
    assert result["subscription_ack"] == "PASS"
    assert result["protocol_error_frames"] == 1
    assert result["protocol_acceptance"] == "FAIL"
    assert result["continuous_feed_qualified"] is False
    assert "DO_NOT_LEAK" not in json.dumps(result)


def test_invalid_ack_followed_by_valid_ack_cannot_be_clean_pass():
    e = ProtocolEvidence(SYMS)
    e.consume({"op": "subscribed", "channel": "depth", "symbols": list(SYMS), "total": 2})
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2})
    summary = e.summary(ws_handshake=True)
    assert summary["subscription_ack"] == "PASS"
    assert summary["protocol_acceptance"] == "FAIL"


def test_valid_ack_is_not_enough_without_handshake():
    e = ProtocolEvidence(SYMS)
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2})
    result = e.summary(ws_handshake=False)
    assert result["subscription_ack"] == "PASS"
    assert result["protocol_acceptance"] == "NOT_VERIFIED"


def test_cli_exit_code_checks_clean_protocol_acceptance_not_ack_alone(monkeypatch, capsys):
    import scripts.tickflow_ws_protocol_probe as target
    monkeypatch.setenv("TICKFLOW_WS_PROTOCOL_PROBE_OPT_IN", "true")
    monkeypatch.setenv("TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED", "true")
    monkeypatch.setenv("TICKFLOW_API_KEY", "DO_NOT_LEAK")
    monkeypatch.setattr(sys, "argv", ["proto", "--execute", "--seconds", "10"])

    async def synthetic_server_error(*_args, **_kwargs):
        return {
            "subscription_ack": "PASS",
            "protocol_error_frames": 1,
            "protocol_acceptance": "FAIL",
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }

    monkeypatch.setattr(target, "run_protocol_probe", synthetic_server_error)
    assert main() == 2
    output = capsys.readouterr().out
    assert '"protocol_acceptance": "FAIL"' in output
    assert "DO_NOT_LEAK" not in output


@pytest.mark.parametrize(
    ("symbols","total"),
    [
        (["159611.SZ", "518880.SH", "512730.SH"], 3),
        (["159611.SZ", "518880.SH", "518880.SH"], 3),
        (["159611.SZ", "518880.SH"], 3),
        (["159611.SZ", "518880.SH"], 1),
    ],
)
def test_ack_with_extras_duplicates_or_bad_total_is_rejected(symbols, total):
    observer = ProtocolEvidence(SYMS)
    observer.consume({
        "op": "subscribed",
        "channel": "quotes",
        "symbols": symbols,
        "total": total,
    })
    result = observer.summary(ws_handshake=True)
    assert result["subscription_ack"] == "NOT_VERIFIED"
    assert result["protocol_acceptance"] == "FAIL"
    assert result["invalid_ack_messages"] == 1
    assert result["radar_admission"] == "BLOCKED"


def test_ack_exact_set_can_arrive_in_different_order():
    observer = ProtocolEvidence(SYMS)
    observer.consume({
        "op": "subscribed",
        "channel": "quotes",
        "symbols": list(reversed(SYMS)),
        "total": 2,
    })
    result = observer.summary(ws_handshake=True)
    assert result["subscription_ack"] == "PASS"
    assert result["protocol_acceptance"] == "PASS"
    assert result["continuous_feed_qualified"] is False


def test_ack_plus_cached_snapshot_is_not_progress_even_after_full_window():
    observer = ProtocolEvidence(SYMS)
    observer.consume({
        "op": "subscribed", "channel": "quotes",
        "symbols": list(SYMS), "total": len(SYMS),
    })
    observer.consume({"op": "quotes", "data": [
        {"symbol": SYMS[0], "timestamp": 1776754800000},
    ]})
    observer.window_status = "COMPLETED"  # isolated no-network observer fixture
    result = observer.summary(ws_handshake=True)
    assert result["protocol_acceptance"] == "PASS"
    assert result["bounded_window_status"] == "COMPLETED"
    assert result["post_initial_progress_status"] == "INSUFFICIENT"
    assert result["continuous_feed_qualified"] is False


def test_two_timestamp_advances_are_progress_not_live_continuity():
    observer = ProtocolEvidence(SYMS)
    observer.consume({
        "op": "subscribed", "channel": "quotes",
        "symbols": list(SYMS), "total": 2,
    })
    for timestamp in (1776754800000, 1776754801000, 1776754802000):
        observer.consume({"op": "quotes", "data": [
            {"symbol": SYMS[0], "timestamp": timestamp},
        ]})
    observer.window_status = "COMPLETED"
    result = observer.summary(ws_handshake=True)
    assert result["post_initial_progress_status"] == "OBSERVED_NOT_QUALIFIED"
    assert result["post_initial_update_candidates"] == 2
    assert result["continuous_feed_qualified"] is False
    assert result["radar_admission"] == "BLOCKED"


def test_early_connection_drop_vetoes_ack_even_after_timestamp_advances():
    observer = ProtocolEvidence(SYMS)
    observer.consume({
        "op": "subscribed", "channel": "quotes",
        "symbols": list(SYMS), "total": 2,
    })
    for timestamp in (1776754800000, 1776754801000, 1776754802000):
        observer.consume({"op": "quotes", "data": [
            {"symbol": SYMS[0], "timestamp": timestamp},
        ]})
    observer.window_status = "TERMINATED_EARLY"
    result = observer.summary(ws_handshake=True)
    assert result["subscription_ack"] == "PASS"
    assert result["post_initial_progress_status"] == "OBSERVED_NOT_QUALIFIED"
    assert result["protocol_acceptance"] == "FAIL"
    assert result["continuous_feed_qualified"] is False


@pytest.mark.parametrize(
    ("protocol", "window", "progress", "expected_code"),
    [
        ("PASS", "COMPLETED", "OBSERVED_NOT_QUALIFIED", 0),
        ("PASS", "COMPLETED", "INSUFFICIENT", 2),
        ("PASS", "TERMINATED_EARLY", "OBSERVED_NOT_QUALIFIED", 2),
        ("FAIL", "COMPLETED", "OBSERVED_NOT_QUALIFIED", 2),
        ("NOT_VERIFIED", "COMPLETED", "OBSERVED_NOT_QUALIFIED", 2),
        ("PASS", "UNOBSERVED", "OBSERVED_NOT_QUALIFIED", 2),
    ],
)
def test_cli_requires_clean_ack_full_window_and_update_progress(
    monkeypatch, capsys, protocol, window, progress, expected_code,
):
    import scripts.tickflow_ws_protocol_probe as target
    monkeypatch.setenv("TICKFLOW_WS_PROTOCOL_PROBE_OPT_IN", "true")
    monkeypatch.setenv("TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED", "true")
    monkeypatch.setenv("TICKFLOW_API_KEY", "DO_NOT_LEAK")
    monkeypatch.setattr(sys, "argv", ["proto", "--execute", "--seconds", "10"])

    async def offline_result(*_args, **_kwargs):
        return {
            "protocol_acceptance": protocol,
            "bounded_window_status": window,
            "post_initial_progress_status": progress,
            "continuous_feed_qualified": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }

    monkeypatch.setattr(target, "run_protocol_probe", offline_result)
    assert main() == expected_code
    output = capsys.readouterr().out
    assert "DO_NOT_LEAK" not in output
    assert '"radar_admission": "BLOCKED"' in output

def test_timestamp_lag_buckets_measure_post_initial_only():
    e = ProtocolEvidence(SYMS)
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2})
    t = 1776754800000
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": t}]}, received_at_ms=t + 300000)
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": t + 1000}]}, received_at_ms=t + 1600)
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": t + 2000}]}, received_at_ms=t + 2900)
    result = e.summary(ws_handshake=True)
    assert result["post_initial_lag_samples"] == 2
    assert result["post_initial_p95_lag_bucket"] == "UNDER_2S"
    assert result["post_initial_future_timestamp_count"] == 0
    assert result["continuous_feed_qualified"] is False

def test_future_clock_mismatch_prevents_latency_freshness_claim():
    e = ProtocolEvidence(SYMS)
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2})
    t = 1776754800000
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": t}]}, received_at_ms=t)
    e.consume({"op": "quotes", "data": [{"symbol": SYMS[0], "timestamp": t+1000}]}, received_at_ms=t-5000)
    result=e.summary(ws_handshake=True)
    assert result["post_initial_lag_samples"] == 1
    assert result["post_initial_p95_lag_bucket"] == "CLOCK_CONFLICT"
    assert result["post_initial_future_timestamp_count"] == 1
