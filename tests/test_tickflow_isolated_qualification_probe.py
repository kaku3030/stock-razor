"""Offline tests for quarantined TickFlow SDK probe with no provider requests."""

import json

import pytest

from scripts import probe_tickflow_isolated as probe


class FakeKlines:
    def get(self, symbol, *, period, count):
        assert symbol in {"159611.SZ", "518880.SH"}
        assert period in {"1d", "1m", "5m", "15m", "30m", "60m"}
        assert count in (3, 5)
        return {
            "timestamp": ["2026-10-09T01:00:00+00:00"],
            "open": [10],
            "high": [11],
            "low": [9],
            "close": [10.5],
            "volume": [100],
            "amount": [1000],
            "api_key": "DO_NOT_LEAK",
        }


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
        self.handlers["quotes"]([
            {
                "symbol": "159611.SZ",
                "last_price": 1,
                "timestamp": 1776754802000,
                "token": "DO_NOT_LEAK",
            },
            {
                "symbol": "159611.SZ",
                "last_price": 1,
                "timestamp": 1776754802000,
                "token": "DO_NOT_LEAK",
            },
        ])
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


def test_kline_summary_is_field_only_and_rejects_bad_ohlcv_order():
    summary = probe._kline_summary([
        {"timestamp": "2026-10-09T01:00:00+00:00", "open": 10, "high": 9,
         "low": 11, "close": "bad", "volume": -1},
        {"timestamp": "2026-10-09T00:59:00+00:00", "open": 10, "high": 12,
         "low": 9, "close": 11, "volume": 1},
    ], period="15m")
    assert summary["sample_count"] == 2
    assert summary["field_presence"] == {
        "timestamp": True, "open": True, "high": True, "low": True,
        "close": True, "volume": True, "amount": False,
    }
    assert summary["numeric_fields"]["close"] is False
    assert summary["timestamp_monotonicity"] == "NOT_MONOTONIC"
    assert summary["ohlcv_range_valid"] == "NOT_VERIFIED"
    assert summary["closure"] == "NOT_VERIFIED"
    assert summary["freshness"] == "NOT_VERIFIED"
    assert summary["entitlement_evidence"] == "UNKNOWN"
    encoded = json.dumps(summary)
    assert '"open": 10' not in encoded
    assert '"close": "bad"' not in encoded


def test_kline_summary_unknown_shape_stays_unverified():
    summary = probe._kline_summary({"provider_payload": "opaque"}, period="60m")
    assert summary["sample_count"] is None
    assert all(value is False for value in summary["field_presence"].values())
    assert summary["timestamp_monotonicity"] == "NOT_VERIFIED"
    assert summary["ohlcv_range_valid"] == "NOT_VERIFIED"
    assert summary["entitlement_evidence"] == "UNKNOWN"


def test_columnar_sdk_kline_shape_gets_row_count_without_payload_output():
    value = {
        "timestamp": [1, 2], "open": [10, 11], "high": [11, 12],
        "low": [9, 10], "close": [10.5, 11.5], "volume": [100, 200],
    }
    assert probe._row_count(value) == 2
    summary = probe._kline_summary(value, period="15m")
    assert summary["sample_count"] == 2
    assert summary["field_presence"]["timestamp"] is True
    assert summary["numeric_fields"]["close"] is True
    assert summary["ohlcv_range_valid"] is True


def test_kline_summary_classifies_ohlcv_failures_without_values():
    summary = probe._kline_summary([
        {"timestamp": 1, "open": 10, "high": 9, "low": 11,
         "close": 10, "volume": -1, "secret": "DO_NOT_LEAK"},
    ], period="15m")
    diagnostics = summary["ohlcv_anomaly_diagnostics"]
    assert summary["ohlcv_range_valid"] is False
    assert diagnostics["status"] == "FAILED"
    assert diagnostics["reasons"] == [
        "HIGH_BELOW_OPEN_OR_CLOSE", "LOW_ABOVE_OPEN_OR_CLOSE",
        "NEGATIVE_VOLUME",
    ]
    assert diagnostics["counts"] == {
        "HIGH_BELOW_OPEN_OR_CLOSE": 1,
        "LOW_ABOVE_OPEN_OR_CLOSE": 1,
        "NEGATIVE_VOLUME": 1,
        "TOLERANCE_PRECISION": 0,
        "COUNT_ONLY": 0,
    }
    assert "DO_NOT_LEAK" not in json.dumps(summary)
    assert '"open": 10' not in json.dumps(summary)


def test_kline_summary_separates_precision_edge_from_material_inconsistency():
    summary = probe._kline_summary([
        {"timestamp": 1, "open": 1.0, "high": 1.0 - 5e-13,
         "low": 1.0, "close": 1.0, "volume": 1},
    ], period="60m")
    diagnostics = summary["ohlcv_anomaly_diagnostics"]
    assert summary["ohlcv_range_valid"] is True
    assert diagnostics["status"] == "PASS"
    assert diagnostics["reasons"] == ["TOLERANCE_PRECISION"]
    assert diagnostics["counts"]["TOLERANCE_PRECISION"] == 1
    assert diagnostics["counts"]["HIGH_BELOW_OPEN_OR_CLOSE"] == 0
    assert diagnostics["counts"]["LOW_ABOVE_OPEN_OR_CLOSE"] == 0


def test_kline_summary_marks_opaque_rows_as_count_only():
    summary = probe._kline_summary(["opaque", "rows"], period="15m")
    diagnostics = summary["ohlcv_anomaly_diagnostics"]
    assert summary["sample_count"] == 2
    assert summary["ohlcv_range_valid"] == "NOT_VERIFIED"
    assert diagnostics["status"] == "NOT_VERIFIED"
    assert diagnostics["reasons"] == ["COUNT_ONLY"]
    assert diagnostics["counts"]["COUNT_ONLY"] == 2


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


def test_premium_contract_missing_credential_and_unknown_gates_is_blocked():
    class NoClient:
        def __init__(self):
            raise AssertionError("Premium contract must not instantiate SDK")

    r = probe.build_probe(
        mode="premium-contract", symbols=("159611.SZ",),
        client_factory=NoClient, credential_present=False,
    )
    contract = r["premium_contract"]
    assert r["operations"] == [{
        "name": "premium_execution_gate",
        "operation": "BLOCKED",
        "reason_codes": [
            "CREDENTIAL_REFERENCE_FAIL",
            "IAM_READ_PERMISSION_UNKNOWN",
            "PROVIDER_ENTITLEMENT_UNKNOWN",
            "PROVIDER_REGION_AUTHORIZED_UNKNOWN",
            "CONCURRENT_USE_AUTHORIZED_UNKNOWN",
            "WEBSOCKET_AUTHORIZED_UNKNOWN",
            "RATE_LIMIT_AUTHORIZED_UNKNOWN",
            "DATA_QUALIFICATION_UNKNOWN",
        ],
    }]
    assert contract["network_execution"] is False
    assert contract["canonical_write"] is False
    assert contract["radar_admission"] == "BLOCKED"
    assert contract["live_trade"] is False


def test_premium_contract_permission_denial_stays_blocked():
    contract = probe.evaluate_premium_execution_gate(
        auth_method=probe.PREMIUM_AUTH_METHOD,
        requested_interfaces=("quotes",),
        credential_reference_available=True,
        iam_read_permission="FAIL",
        provider_entitlement="PASS",
        provider_region_authorized="PASS",
        concurrent_use_authorized="PASS",
        websocket_authorized="PASS",
        rate_limit_authorized="PASS",
        data_qualification="PASS",
    )
    assert contract["premium_execution"] == "BLOCKED"
    assert contract["blocked_reasons"] == ["IAM_READ_PERMISSION_FAIL"]


@pytest.mark.parametrize("kwargs", [
    {"auth_method": "STATIC_API_KEY"},
    {"requested_interfaces": ("orders",)},
    {"data_qualification": "INVALID"},
])
def test_premium_contract_configuration_errors_fail_closed(kwargs):
    defaults = {
        "auth_method": probe.PREMIUM_AUTH_METHOD,
        "requested_interfaces": ("quotes",),
        "credential_reference_available": True,
        "iam_read_permission": "PASS",
        "provider_entitlement": "PASS",
        "provider_region_authorized": "PASS",
        "concurrent_use_authorized": "PASS",
        "websocket_authorized": "PASS",
        "rate_limit_authorized": "PASS",
        "data_qualification": "PASS",
    }
    defaults.update(kwargs)
    with pytest.raises(ValueError):
        probe.evaluate_premium_execution_gate(**defaults)


def test_cli_dependency_failure_exits_nonzero_without_leaking(monkeypatch, capsys):
    import sys

    def missing_package(_name):
        raise probe.importlib.metadata.PackageNotFoundError("tickflow")

    monkeypatch.setattr(probe.importlib.metadata, "version", missing_package)
    monkeypatch.setattr(sys, "argv", ["probe", "--mode", "free"])
    assert probe.main() == 2
    output = capsys.readouterr().out
    assert '"setup_state": "BLOCKED"' in output
    assert "PackageNotFoundError" in output
    assert "API_KEY" not in output


def test_premium_rest_smoke_is_redacted_and_not_radar_authority():
    r = probe.build_probe(
        mode="premium", symbols=("159611.SZ", "518880.SH"),
        client_factory=FakeClient, credential_present=True,
    )
    names = [x["name"] for x in r["operations"]]
    assert names == [
        "sdk_import", "realtime_quote", "kline_1m", "kline_5m",
        "kline_15m", "kline_15m", "kline_30m", "kline_60m", "kline_60m",
        "five_level_depth",
        "websocket_quote_smoke",
    ]
    assert r["operations"][-1]["operation"] == "SKIPPED"
    assert all(x.get("schema_qualified") is not True for x in r["operations"])
    kline_ops = [
        x for x in r["operations"] if x["name"] in {"kline_15m", "kline_60m"}
    ]
    assert [(x["name"], x["symbol"]) for x in kline_ops] == [
        ("kline_15m", "159611.SZ"),
        ("kline_15m", "518880.SH"),
        ("kline_60m", "159611.SZ"),
        ("kline_60m", "518880.SH"),
    ]
    for operation in kline_ops:
        summary = operation["summary"]
        assert summary["sample_count"] == 1
        assert summary["field_presence"]["close"] is True
        assert summary["numeric_fields"]["volume"] is True
        assert summary["ohlcv_range_valid"] is True
        assert summary["closure"] == "NOT_VERIFIED"
        assert summary["freshness"] == "NOT_VERIFIED"
        assert summary["entitlement_evidence"] == "UNKNOWN"
    encoded = json.dumps(r)
    assert "DO_NOT_LEAK" not in encoded
    assert "last_price" not in encoded
    assert '"close": 10.5' not in encoded
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
    assert ws["quote_events"] == 2
    assert ws["connection_call"] == "PASS"
    assert ws["connection_state"] == "UNKNOWN"
    assert ws["subscription_call"] == "PASS"
    assert ws["subscription_state"] == "UNKNOWN"
    assert ws["event_state"] == "PASS"
    assert ws["unique_quote_samples"] == 1
    assert ws["initial_snapshot_candidates"] == 1
    assert ws["duplicate_timestamp_events"] == 1
    assert ws["arrival_minus_provider_timestamp_ms"]["count"] == 0
    assert ws["first_per_symbol_cache_candidate_age_ms"]["count"] == 1
    assert ws["subscribed_ack_evidence"] == "NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK"
    assert ws["sample_latency_qualification"] == "NOT_VERIFIED"
    assert ws["clock_offset_qualification"] == "NOT_VERIFIED"
    assert ws["error_callbacks"] == 1
    assert ws["continuous_feed_qualified"] is False
    assert ws["stale_drop_reconnect_qualified"] is False
    assert "DO_NOT_LEAK" not in json.dumps(r)


def test_ws_diagnostics_keep_connection_failure_separate_from_subscription(monkeypatch):
    class ConnectFailureStream(FakeStream):
        def connect(self, block=True):
            raise ConnectionError("DO_NOT_LEAK")

    client = FakeClient()
    client.stream = ConnectFailureStream()
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: None)
    ws = probe.build_probe(
        mode="premium", symbols=("159611.SZ", "518880.SH"),
        ws_seconds=1, client_factory=lambda: client,
        credential_present=True,
    )["operations"][-1]

    assert ws["subscription_call"] == "PASS"
    assert ws["subscription_state"] == "UNKNOWN"
    assert ws["connection_call"] == "FAIL"
    assert ws["connection_state"] == "FAIL"
    assert ws["event_state"] == "UNKNOWN"
    assert ws["quote_events"] == 0
    assert ws["failure_class"] == "ConnectionError"


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


def test_ws_initial_snapshot_is_not_used_as_live_lag_and_events_are_bounded(monkeypatch):
    class MixedStream(FakeStream):
        def connect(self, block=True):
            assert block is False
            self.handlers["quotes"]([
                {"symbol": "159611.SZ", "timestamp": 1760000000000, "token": "DO_NOT_LEAK"},
                {"symbol": "518880.SH", "timestamp": 1760000000, "token": "DO_NOT_LEAK"},
            ])
            self.handlers["quotes"]([
                {"symbol": "159611.SZ", "timestamp": 1760000001000, "token": "DO_NOT_LEAK"},
                {"symbol": "159611.SZ", "timestamp": 1760000001000},
                {"symbol": "159611.SZ", "timestamp": 1759999999000},
                {"symbol": "159611.SZ", "timestamp": float("nan")},
                {"symbol": "999999.SZ", "timestamp": 1760000002000},
                {"symbol": "518880.SH", "timestamp": 1760000001000},
            ])

    c = FakeClient()
    c.stream = MixedStream()
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: None)
    result = probe.build_probe(
        mode="premium", symbols=("159611.SZ", "518880.SH"),
        ws_seconds=1, client_factory=lambda: c, credential_present=True,
    )
    ws = result["operations"][-1]
    assert ws["quote_callbacks"] == 2
    assert ws["quote_events"] == 8
    assert ws["connection_state"] == "UNKNOWN"
    assert ws["subscription_state"] == "UNKNOWN"
    assert ws["event_state"] == "PASS"
    assert ws["initial_snapshot_candidates"] == 2
    assert ws["post_initial_update_candidates"] == 2
    assert ws["duplicate_timestamp_events"] == 1
    assert ws["out_of_order_timestamp_events"] == 1
    assert ws["invalid_timestamp_events"] == 1
    assert ws["unrequested_symbol_events"] == 1
    assert ws["unique_quote_samples"] == 4
    assert ws["first_per_symbol_cache_candidate_age_ms"]["count"] == 2
    assert ws["arrival_minus_provider_timestamp_ms"]["count"] == 2
    assert ws["lag_scope"] == "POST_INITIAL_CANDIDATES_ONLY_NOT_VERIFIED_LIVE"
    assert ws["sample_latency_qualification"] == "NOT_VERIFIED"
    assert ws["clock_offset_qualification"] == "NOT_VERIFIED"
    assert ws["snapshot_vs_live_evidence"] == "NOT_VERIFIED"
    assert ws["ping_pong_evidence"] == "NOT_VERIFIED"
    assert ws["reconnect_resubscribe_evidence"] == "NOT_VERIFIED"
    assert ws["continuous_feed_qualified"] is False
    assert ws["stale_drop_reconnect_qualified"] is False
    assert c.stream.closed
    assert "DO_NOT_LEAK" not in json.dumps(result)


def test_ws_quote_with_boolean_or_non_finite_timestamp_is_never_age_sample(monkeypatch):
    class InvalidStream(FakeStream):
        def connect(self, block=True):
            self.handlers["quotes"]([
                {"symbol": "159611.SZ", "timestamp": True},
                {"symbol": "159611.SZ", "timestamp": -1},
                {"symbol": "159611.SZ", "timestamp": float("inf")},
                {"symbol": "159611.SZ", "timestamp": None},
                {"symbol": "159611.SZ", "timestamp": 1760000000000},
            ])

    c = FakeClient()
    c.stream = InvalidStream()
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: None)
    ws = probe.build_probe(
        mode="premium", symbols=("159611.SZ", "518880.SH"),
        ws_seconds=1, client_factory=lambda: c, credential_present=True,
    )["operations"][-1]
    assert ws["invalid_timestamp_events"] == 4
    assert ws["connection_state"] == "UNKNOWN"
    assert ws["subscription_state"] == "UNKNOWN"
    assert ws["event_state"] == "PASS"
    assert ws["initial_snapshot_candidates"] == 1
    assert ws["arrival_minus_provider_timestamp_ms"]["count"] == 0
    assert ws["sample_latency_qualification"] == "NOT_VERIFIED"
