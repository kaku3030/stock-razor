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

def test_dominant_current_day_quarantine_cause_is_enum_only():
    import scripts.audit_cn_tickflow_research_runtime as audit
    from datetime import datetime, timezone
    frame={"rows":[{"label":"2026-10-13 09:45",
                    "amount_availability":"PRESENT_UNVERIFIED",
                    "close":99999999.0} for _ in range(4)],
           "quarantined_unverified_rows_count":3,
           "quarantine_reason_counts":{
                "TODAY_NONPOSITIVE_OHLC":2,"TODAY_LABEL_OFF_GRID":1,
           }}
    result=audit.summarize_private_frame_progress(frame,timeframe="15m",
         now_utc=datetime(2026,10,13,7,10,tzinfo=timezone.utc))
    assert result["dominant_quarantine_reason"]=="TODAY_NONPOSITIVE_OHLC"
    assert "99999999" not in str(result)
    malicious={**frame,"quarantine_reason_counts":{
        "API_KEY=secret":3}}
    bad=audit.summarize_private_frame_progress(malicious,timeframe="15m",
         now_utc=datetime(2026,10,13,7,10,tzinfo=timezone.utc))
    assert bad["dominant_quarantine_reason"]=="UNKNOWN"

def test_cloud_audit_ohlc_gap_severity_is_enum_only_no_prices():
    from datetime import datetime, timezone
    import scripts.audit_cn_tickflow_research_runtime as monitor
    frame={"rows":[{"label":"2026-10-13 14:45",
                    "amount_availability":"PRESENT_UNVERIFIED",
                    "close":92881923.123} for _ in range(4)],
           "quarantined_unverified_rows_count":3,
           "quarantine_reason_counts":{"TODAY_HIGH_BELOW_BODY":3},
           "quarantine_ohlc_gap_evidence":{
               "GAP_LT_1BP":2,
               "GAP_GE_100BP":1,
               "HILO_SWAP_WOULD_ENCLOSE_BODY":1,
           }}
    now=datetime(2026,10,13,7,10,tzinfo=timezone.utc)
    result=monitor.summarize_private_frame_progress(
        frame,timeframe="15m",now_utc=now,
    )
    assert result["largest_ohlc_gap_bucket"]=="GAP_GE_100BP"
    assert result["gap_violation_rows_bucket"]=="TWO_TO_FOUR"
    assert result["hilo_swap_candidate_bucket"]=="ONE"
    assert "92881923" not in str(result)
    malicious={**frame,"quarantine_ohlc_gap_evidence":{"APIKEY=SECRET":2}}
    restricted=monitor.summarize_private_frame_progress(
        malicious,timeframe="15m",now_utc=now,
    )
    assert restricted["largest_ohlc_gap_bucket"]=="UNKNOWN"
