"""Offline tests for quarantined TickFlow SDK probe with no provider requests."""

import json

import pytest

from scripts import probe_tickflow_isolated as probe


class FakeKlines:
    def get(self, symbol, *, period, count):
        assert symbol == "159611.SZ"
        assert period in {"1d", "1m", "5m", "15m", "30m", "60m"}
        assert count in (3, 5)
        return [{"symbol": symbol, "close": 999, "api_key": "DO_NOT_LEAK"}]


class FakeQuotes:
    def get(self, *, symbols):
        assert symbols == ["159611.SZ", "518880.SH"]
        return [{"symbol": symbols[0], "last_price": 88, "token": "DO_NOT_LEAK"}]


class FakeDepth:
    def get(self, symbol):
        return {"symbol": symbol, "bid_prices": [1.0], "token": "DO_NOT_LEAK"}


class FakeStream:
    def __init__(self):
        self.handlers = {}
        self.closed = False

    def on_quotes(self, f):
        self.handlers["quotes"] = f
        return f

    def on_error(self, f):
        self.handlers["error"] = f
        return f

    def subscribe(self, channel, symbols):
        assert channel == "quotes"
        assert symbols == ["159611.SZ", "518880.SH"]

    def connect(self, block=True):
        assert block is False
        self.handlers["quotes"]([{"last_price": 1, "token": "DO_NOT_LEAK"}])
        self.handlers["error"]("DO_NOT_LEAK")

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self):
        self.klines = FakeKlines()
        self.quotes = FakeQuotes()
        self.depth = FakeDepth()
        self.stream = FakeStream()

    @classmethod
    def free(cls):
        return cls()


@pytest.mark.parametrize("bad", [
    "159611", "US.AMD", "000001.US", "59.SZ", "159611.HK",
    "159611.SZ;EXECUTE", "  ", "../../.env",
])
def test_symbols_are_cn_only_and_cannot_be_shell_expressions(bad):
    with pytest.raises(ValueError):
        probe.validate_symbols([bad])


def test_symbols_are_normalized_and_count_is_bounded():
    assert probe.validate_symbols(["159611.sz", "518880.SH"]) == (
        "159611.SZ", "518880.SH"
    )
    with pytest.raises(ValueError):
        probe.validate_symbols(["159611.SZ"] * 6)
    with pytest.raises(ValueError):
        probe.validate_symbols([])


def test_metadata_never_calls_provider_even_if_key_present():
    class NoNetwork:
        def __init__(self):
            raise AssertionError("Must not instantiate SDK")

        @classmethod
        def free(cls):
            raise AssertionError("Must not call SDK")
    r = probe.build_probe(
        mode="metadata", symbols=("159611.SZ",),
        client_factory=NoNetwork, sdk_version="0.1.25",
        credential_present=True,
    )
    assert [x["name"] for x in r["operations"]] == ["sdk_import"]
    assert r["api_key_present"] is True
    assert r["data_qualification"] == "NOT_VERIFIED"
    assert r["radar_admission"] == "BLOCKED"
    assert r["canonical_write"] is False
    assert r["order_execution"] is False


def test_free_daily_probe_does_not_require_key_or_claim_minute_service():
    r = probe.build_probe(
        mode="free", symbols=("159611.SZ",),
        client_factory=FakeClient, sdk_version="0.1.25",
        credential_present=False,
    )
    names = [x["name"] for x in r["operations"]]
    assert names == ["sdk_import", "free_daily_kline"]
    assert r["operations"][-1]["row_count"] == 1
    assert r["operations"][-1]["schema_qualified"] is False


def test_premium_missing_key_is_skipped_without_sdk_calls():
    class NoClient:
        def __init__(self):
            raise AssertionError("No premium without credentials")
    r = probe.build_probe(
        mode="premium", symbols=("159611.SZ",),
        client_factory=NoClient, credential_present=False,
    )
    assert r["operations"][-1] == {
        "name": "premium_probe",
        "operation": "SKIPPED",
        "reason": "NO_API_KEY",
    }
    assert r["real_market_slo"] == "NOT_VERIFIED"


def test_premium_rest_smoke_is_redacted_and_not_radar_authority():
    r = probe.build_probe(
        mode="premium", symbols=("159611.SZ", "518880.SH"),
        client_factory=FakeClient, credential_present=True,
    )
    names = [x["name"] for x in r["operations"]]
    assert names == [
        "sdk_import", "realtime_quote", "kline_1m", "kline_5m",
        "kline_15m", "kline_30m", "kline_60m", "five_level_depth",
        "websocket_quote_smoke",
    ]
    assert r["operations"][-1]["operation"] == "SKIPPED"
    assert all(x.get("schema_qualified") is not True for x in r["operations"])
    encoded = json.dumps(r)
    assert "DO_NOT_LEAK" not in encoded
    assert "last_price" not in encoded
    assert "close" not in encoded
    assert "bid_prices" not in encoded
    assert r["can_confirm_signal"] is False
    assert r["source_arbiter_admission"] == "BLOCKED"


def test_ws_smoke_tracks_callbacks_but_never_promotes_stream(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: None)
    r = probe.build_probe(
        mode="premium", symbols=("159611.SZ", "518880.SH"),
        ws_seconds=1, client_factory=lambda: fake,
        credential_present=True,
    )
    ws = r["operations"][-1]
    assert fake.stream.closed is True
    assert ws["quote_events"] == 1
    assert ws["error_callbacks"] == 1
    assert ws["continuous_feed_qualified"] is False
    assert ws["stale_drop_reconnect_qualified"] is False
    assert "DO_NOT_LEAK" not in json.dumps(r)


def test_ws_requires_explicit_premium_and_bounded_duration():
    for mode in ("free", "metadata"):
        with pytest.raises(ValueError):
            probe.build_probe(mode=mode, symbols=("159611.SZ",), ws_seconds=1)
    with pytest.raises(ValueError):
        probe.build_probe(mode="premium", symbols=("159611.SZ",), ws_seconds=16)


def test_provider_exceptions_are_class_only_not_secret_bodies():
    result = probe._operation(
        "probe",
        lambda: (_ for _ in ()).throw(RuntimeError("api_key=SHOULD_NOT_PRINT")),
    )
    assert result["failure_class"] == "RuntimeError"
    assert "SHOULD_NOT_PRINT" not in json.dumps(result)
    assert result["operation"] == "FAILED"


def test_sdk_chinese_console_notice_is_suppressed_and_no_payload_printed(capsys):
    class NoisyFreeClient(FakeClient):
        @classmethod
        def free(cls):
            print("免费数据提示：KEY_DO_NOT_LEAK")
            return cls()

    result = probe.build_probe(
        mode="free", symbols=("159611.SZ",),
        client_factory=NoisyFreeClient, credential_present=False,
    )
    assert result["operations"][-1]["operation"] == "COMPLETED"
    assert capsys.readouterr().out == ""
    assert "KEY_DO_NOT_LEAK" not in json.dumps(result)


def test_operation_stdout_stderr_are_suppressed_even_on_failure(capsys):
    import sys
    def bad_provider():
        print("KEY_DO_NOT_LEAK")
        print("SECRET_FAILURE_BODY", file=sys.stderr)
        raise RuntimeError("DO_NOT_PRINT_ERROR_BODY")
    result = probe._operation("provider", bad_provider)
    assert result["failure_class"] == "RuntimeError"
    captured=capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "DO_NOT_PRINT_ERROR_BODY" not in json.dumps(result)
