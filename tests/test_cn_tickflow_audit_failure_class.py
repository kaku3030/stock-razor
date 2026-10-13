from scripts.audit_cn_tickflow_research_runtime import blocked_status

def test_diagnostic_enum_only_never_leaks_arbitrary_messages():
    assert blocked_status("ValueError")=="BLOCKED_VALUE_ERROR"
    assert blocked_status("TypeError")=="BLOCKED_TYPE_ERROR"
    assert blocked_status("RateLimitError")=="BLOCKED_RATE_LIMIT_ERROR"
    assert blocked_status("KeyError\\nSECRET_API_KEY=private")=="BLOCKED_OTHER"
    assert blocked_status(None)=="BLOCKED_OTHER"
    assert blocked_status({"api_key":"secret"})=="BLOCKED_OTHER"

def test_stage_projection_uses_fixed_provider_scope_only():
    from scripts.audit_cn_tickflow_research_runtime import blocked_status
    assert blocked_status("ValueError")=="BLOCKED_VALUE_ERROR"

def test_production_mcp_failure_diagnostics_never_return_stdout_errors():
    from pathlib import Path
    root=Path(__file__).resolve().parent.parent
    source=(root/"scripts/audit_cn_tickflow_research_runtime.py").read_text(encoding="utf-8")
    workflow=(root/".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    assert "METHOD_RETURN_BLOCKED" in source
    assert "IMPORT_OR_RUNTIME_FAILURE" in source
    assert "mcp_read_failure_reason" in workflow
    assert "period_status" in workflow
    assert "StandardErrorContent" not in workflow
    assert "CN_TICKFLOW_AWS_RESEARCH_SANITIZED=" in workflow
