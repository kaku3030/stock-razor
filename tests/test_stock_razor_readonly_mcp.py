from realtime_monitor import stock_razor_readonly_mcp as server


def test_tools_are_read_only_and_preserve_unknown_gate_fields(monkeypatch):
    monkeypatch.setenv(server.API_BASE_ENV, "https://snapshot.example")
    monkeypatch.setenv(server.TOKEN_ENV, "test-only-token")
    calls = []

    def fake_get(path):
        calls.append(path)
        return {
            "symbol": "AMD",
            "provider": "futu-opend",
            "feed": "us",
            "entitlement": "UNKNOWN",
            "quote": {
                "source_timestamp": "2026-09-30T13:30:00Z",
                "received_at": "2026-09-30T13:30:01Z",
                "observed_latency_ms": 1000,
                "quality_flags": ["BAR_DERIVED_PRICE"],
            },
            "bars": [{
                "timeframe": "1m",
                "source_timestamp": "2026-09-30T13:30:00Z",
                "received_at": "2026-09-30T13:30:01Z",
                "quality_flags": ["BAR_DERIVED_PRICE"],
            }],
            "evidence": {"runtime_generation": 2},
        }

    monkeypatch.setattr(server, "_get", fake_get)
    result = server.get_market_snapshots(["amd", "AMD"], "1m")

    assert calls == ["/api/v1/data/market-snapshot/AMD"]
    assert result["read_only"] is True
    row = result["snapshots"][0]
    assert row["provider"] == "futu-opend"
    assert row["runtime_generation"] == 2
    assert row["provider_finality"] == "UNKNOWN"
    assert row["currentness"] == "UNKNOWN"


def test_base_url_requires_https(monkeypatch):
    monkeypatch.setenv(server.API_BASE_ENV, "http://localhost:8000")
    try:
        server._base_url()
    except RuntimeError as error:
        assert "HTTPS" in str(error)
    else:
        raise AssertionError("insecure API URL was accepted")
