import json

from scripts.sanitize_ssm_probe_output import project


def test_projection_keeps_bar_freshness_but_drops_raw_market_payload() -> None:
    raw = json.dumps({
        "probe": "us_livefeed_status",
        "schema": "safe-v1",
        "emitted_at_utc": "2026-10-13T13:00:00Z",
        "symbols": {
            "US.AMD": {"timeframes": {
                "5m": {"count": 12, "latest_end_utc": "2026-10-13T12:55:00Z"},
            }},
        },
        "close": 123.45,
        "volume": 999,
        "runtime_instance_id": "private-instance",
    })
    result = "\n".join(project(raw))
    assert "SANITIZED_PROBE" in result
    assert "symbol_count" in result
    assert "latest_end_utc" in result
    assert "123.45" not in result
    assert "999" not in result
    assert "private-instance" not in result


def test_projection_keeps_fixed_status_lines_only() -> None:
    result = "\n".join(project(
        "SUBSCRIPTION=PASS\nUS_QOT_RIGHT=UNKNOWN\nSUBSCRIPTION=secret-token\nACCOUNT_ID=private\n"
    ))
    assert "SUBSCRIPTION=PASS" in result
    assert "US_QOT_RIGHT=UNKNOWN" in result
    assert "secret-token" not in result
    assert "ACCOUNT_ID" not in result


def test_public_projection_rejects_remote_urls_paths_and_untrusted_bar_keys() -> None:
    raw = json.dumps({
        "probe": "us_livefeed_status",
        "reason": "https://private-internal.example/access",
        "mcp_protocol_endpoint": "https://internal.example/secret-path",
        "runtime_git_worktree": "C:/Users/private/repository",
        "status": 987654321,
        "sequence": 42,
        "symbols": {"PRIVATE_SYMBOL": {"timeframes": {
            "ACCOUNT_ID_99999": {"count": 12, "latest_end_utc": "2026-10-13T13:00:00Z"},
            "5m": {"count": "9876543210", "latest_end_utc": "2026-10-13T13:00:00Z"},
            "15m": {"count": 2, "latest_end_utc": "https://internal.example"},
            "1H": {"count": 4, "latest_end_utc": "2026-10-13T12:00:00Z"},
        }}},
    })
    result = "\n".join(project(raw))
    assert '"sequence":42' in result
    assert '"1H"' in result
    assert "2026-10-13T12:00:00Z" in result
    for secret in ("private-internal", "internal.example", "PRIVATE_SYMBOL",
                   "ACCOUNT_ID_99999", "9876543210", "987654321",
                   "C:/Users/private"):
        assert secret not in result


def test_public_projection_denies_non_enumerated_stdout_strings() -> None:
    result = "\n".join(project(
        "US_QOT_RIGHT=REALTIME\n"
        "MCP_PROTOCOL_ENDPOINT=https://internal.example/private\n"
        "SUBSCRIPTION=C:/private/output\n"
        "SUBSCRIPTION=PASS\n"
        "TRADE_EXECUTION=NO\n"
    ))
    assert "US_QOT_RIGHT=REALTIME" in result
    assert "SUBSCRIPTION=PASS" in result
    assert "TRADE_EXECUTION=NO" in result
    assert "internal.example" not in result
    assert "C:/private" not in result


def test_projector_does_not_claim_market_acceptance(monkeypatch, capsys) -> None:
    from io import StringIO
    from scripts.sanitize_ssm_probe_output import main
    import sys
    monkeypatch.setattr(sys, "argv", ["sanitize_ssm_probe_output.py", "--action", "opend_status"])
    monkeypatch.setattr(sys, "stdin", StringIO("SUBSCRIPTION=PASS\n"))
    assert main() == 0
    assert "SANITIZED_EVIDENCE=AVAILABLE_NOT_QUALIFIED" in capsys.readouterr().out
