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


def test_failed_ssm_keeps_only_fixed_mcp_stage_enums_and_no_remote_errors() -> None:
    text = (
        "MCP_INITIALIZE=FAIL\n"
        "MCP_TOOL_SURFACE_MISMATCH=FAIL\n"
        "PRIVATE_MCP_TOOL_DISCOVERY_8_OF_8=FAIL\n"
        "MCP_PROTOCOL_TOOL_CALL_FAILED=YES\n"
        "MCP_LIST_TOOLS=PASS\n"
        "MCP_PROCESS_PID=9783\n"
        "MCP_INITIALIZE_DETAIL=https://internal.invalid/secrets\n"
        "MCP_PROBE_REASON=Bearer PRIVATE_API_KEY\n"
        "ACCOUNT_ID=12345678\n"
    )
    output = "\n".join(project(text))
    for fact in (
        "MCP_INITIALIZE=FAIL", "MCP_TOOL_SURFACE_MISMATCH=FAIL",
        "PRIVATE_MCP_TOOL_DISCOVERY_8_OF_8=FAIL",
        "MCP_PROTOCOL_TOOL_CALL_FAILED=YES", "MCP_LIST_TOOLS=PASS",
    ):
        assert fact in output
    for item in ("internal.invalid", "PRIVATE_API_KEY", "9783", "12345678", "MCP_INITIALIZE_DETAIL"):
        assert item not in output


def test_failed_ssm_cli_marks_diagnostics_not_admission(monkeypatch, capsys) -> None:
    from io import StringIO
    from scripts.sanitize_ssm_probe_output import main
    import sys
    monkeypatch.setattr(sys, "argv", [
        "sanitize_ssm_probe_output.py", "--action", "mcp_protocol_probe", "--failed-status"
    ])
    monkeypatch.setattr(sys, "stdin", StringIO(
        "MCP_INITIALIZE=FAIL\n"
        "MCP_INITIALIZE_DETAIL=Bearer secret\n"
    ))
    assert main() == 0
    output = capsys.readouterr().out
    assert "SANITIZED_EVIDENCE=FAILED_COMMAND_ENUMS_ONLY" in output
    assert "MCP_INITIALIZE=FAIL" in output
    assert "Bearer" not in output


def test_ssm_failed_branch_preserves_nonzero_ci_and_filters_private_stdout() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/aws-ssm-ops.yml").read_text(encoding="utf-8")
    start = workflow.index("              Failed|Cancelled|TimedOut|Cancelling)")
    end = workflow.index("            esac", start)
    failed = workflow[start:end]
    assert "StandardOutputContent --output text" in failed
    assert "scripts/sanitize_ssm_probe_output.py" in failed
    assert "--failed-status" in failed
    assert "exit 1" in failed
    assert "StandardErrorContent" not in failed

 
def test_opend_subscription_audit_projects_only_bounded_tracked_evidence() -> None:
    raw = json.dumps({
        "probe": "us_opend_subscription_audit_v0_1",
        "query_status": "PASS",
        "opend_reachable": True,
        "quota_verified": True,
        "subscription_capacity": {"remain": 17, "total_used": 3, "private": 991},
        "subscribed_tracked": ["US.AMD", "US.QQQ"],
        "unsubscribed_tracked": ["US.NVDA"],
        "subscription_types": {
            "K_1M": {"tracked_count": 1, "tracked_codes": ["US.AMD"],
                    "private": "provider text"},
            "PRIVATE_TYPE": {"tracked_count": 1, "tracked_codes": ["US.NVDA"]},
        },
        "provider_payload": "private-account-secret",
        "live_trade": False,
    })
    output = "\\n".join(project(raw, "us_opend_subscription_audit"))
    assert '"quota_verified":true' in output
    assert '"subscription_capacity":{"remain":17,"total_used":3}' in output
    assert '"subscribed_tracked":["US.AMD","US.QQQ"]' in output
    assert '"unsubscribed_tracked":["US.NVDA"]' in output
    assert '"K_1M":{"tracked_codes":["US.AMD"],"tracked_count":1}' in output
    for secret in ("private-account-secret", "PRIVATE_TYPE", "991", "provider text"):
        assert secret not in output


def test_opend_subscription_details_are_not_projected_for_other_actions() -> None:
    raw = json.dumps({
        "probe": "us_opend_subscription_audit_v0_1",
        "subscribed_tracked": ["US.AMD"],
        "subscription_capacity": {"remain": 17, "total_used": 3},
    })
    output = "\\n".join(project(raw, "us_livefeed_status"))
    assert "subscribed_tracked" not in output
    assert "subscription_capacity" not in output


def test_opend_subscription_projection_rejects_unbounded_or_inconsistent_fields() -> None:
    raw = json.dumps({
        "probe": "us_opend_subscription_audit_v0_1",
        "subscription_capacity": {"remain": -1, "total_used": 3},
        "subscribed_tracked": ["US.AMD", "US.PRIVATE"],
        "unsubscribed_tracked": ["US.NVDA"],
        "subscription_types": {
            "K_1M": {"tracked_count": 2, "tracked_codes": ["US.AMD"]},
        },
    })
    output = "\\n".join(project(raw, "us_opend_subscription_audit"))
    assert "subscription_capacity" not in output
    assert '"subscribed_tracked"' not in output
    assert "subscription_types" in output
    assert "unsubscribed_tracked" in output
