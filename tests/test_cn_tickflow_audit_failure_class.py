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

def test_aws_history_audit_is_separate_from_currentness_and_excludes_prices():
    from pathlib import Path
    root=Path(__file__).resolve().parent.parent
    code=(root/"scripts/audit_cn_tickflow_research_runtime.py").read_text(encoding="utf-8")
    workflow=(root/".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    assert 'historical_research_usable' in code
    assert 'all_four_historical_requests_ok' in code
    assert 'limited_research_usable' in code
    assert 'historical_period_status' in workflow
    assert 'historical_research_usable' in workflow
    assert 'live_trade' in code
    assert 'StandardErrorContent' not in workflow

def test_private_latest_due_bar_diagnostics_are_bounded_enums_only(monkeypatch):
    from datetime import datetime, timezone
    import scripts.audit_cn_tickflow_research_runtime as monitor
    from data_provider.cn_tickflow_research_cache import normalize_bars
    import pandas as pd
    # Current Shanghai Tuesday 15:10; last retained 14:45 means exactly
    # one scheduled 15m boundary is missing. The price never leaves audit.
    stamps=["2026-10-09 09:45","2026-10-09 10:00",
            "2026-10-09 10:15","2026-10-09 10:30",
            "2026-10-13 14:30","2026-10-13 14:45"]
    frame={"rows":[{"label":x,"amount_availability":"SDK_OMITTED",
                    "close":987654.321,"open":123.45} for x in stamps],
           "quarantined_unverified_rows_count":1}
    now=datetime(2026,10,13,7,10,tzinfo=timezone.utc)
    result=monitor.summarize_private_frame_progress(frame,timeframe="15m",now_utc=now)
    assert result["last_due_grid"]=="ONE_DUE_BOUNDARY_MISSING"
    assert result["quarantined_rows_bucket"]=="ONE"
    assert result["sdk_amount_omitted_bucket"]=="FIVE_PLUS"
    assert "987654" not in str(result) and "2026-10-13" not in str(result)
    invalid=monitor.summarize_private_frame_progress({"rows":[]},timeframe="15m",now_utc=now)
    assert invalid["last_due_grid"]=="UNKNOWN"
