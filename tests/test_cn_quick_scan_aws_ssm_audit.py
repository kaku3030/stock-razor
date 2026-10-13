"""Contract guards for the bounded AWS CN Quick Scan read-only audit."""
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "aws-ssm-ops.yml"
).read_text(encoding="utf-8")


def _audit_case() -> str:
    start = WORKFLOW.index("            cn_quick_scan_audit)")
    end = WORKFLOW.index("            tickflow_mcp_cache_audit)", start)
    return WORKFLOW[start:end]


def test_audit_is_explicitly_available_and_one_fixed_case():
    assert WORKFLOW.count("          - cn_quick_scan_audit\n") == 1
    assert WORKFLOW.count("            cn_quick_scan_audit)") == 1
    assert "commands.json" in _audit_case()
    assert 'jq -c -n --arg script "$cn_quick_scan_audit_script"' in _audit_case()


def test_audit_is_read_only_bounded_and_uses_live_installed_mcp():
    case = _audit_case()
    assert "systemctl is-active stock-razor-mcp.service" in case
    assert "timeout 12s env PYTHONPATH=" in case
    assert "from realtime_monitor.readonly_mcp_server import get_cn_quick_scan, mcp" in case
    assert 'get_cn_quick_scan(["159611", "512730"])' in case
    assert '"get_cn_quick_scan" in mcp._tool_manager._tools' in case
    for forbidden in ("systemctl restart", "systemctl stop", "pip install",
                      "aws secretsmanager", "broker.place_order"):
        assert forbidden not in case


def test_safety_and_no_provider_io_guards_remain_strict():
    case = _audit_case()
    for expected in (
        'assert result.get("research_only") is True',
        'assert result.get("can_confirm_signal") is False',
        'assert result.get("entry_gate") == "ENTRY_BLOCKED"',
        'assert result.get("radar_admission") == "BLOCKED"',
        'assert result.get("live_trade") is False',
        'assert result.get("provider_requests") == 0',
        "LIVE_TRADE=NO",
    ):
        assert expected in case


def test_evidence_labels_are_server_measurements_not_user_delivery():
    case = _audit_case()
    assert '"reader_total_ms": perf.get("reader_total_ms")' in case
    assert '"market_age_seconds": source.get("market_age_seconds")' in case
    assert '"radar_analysis_ms": perf.get("radar_analysis_ms")' in case
    assert '"status": result.get("status")' in case
    assert "user_visible_total_ms" not in case
    assert "chatgpt_analysis_ms" not in case
