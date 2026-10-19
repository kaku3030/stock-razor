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

def test_etf_lattice_quantization_compatibility_audit_has_no_price_data():
    from datetime import datetime,timezone
    import scripts.audit_cn_tickflow_research_runtime as audit
    raw={"rows":[{"label":"2026-10-13 14:45",
                  "amount_availability":"PRESENT_UNVERIFIED",
                  "open":9999999.12} for _ in range(4)],
         "quarantined_unverified_rows_count":3,
         "quarantine_reason_counts":{"TODAY_HIGH_BELOW_BODY":3},
         "quarantine_ohlc_gap_evidence":{
             "GAP_LT_1BP":3,
             "ETF_TICK_LATTICE_NEAR":2,
             "ETF_TICK_LATTICE_FAR":1,
             "ETF_LATTICE_QUANTIZE_WOULD_ENCLOSE_BODY":2,
         }}
    now=datetime(2026,10,13,7,10,tzinfo=timezone.utc)
    observed=audit.summarize_private_frame_progress(raw,timeframe="15m",now_utc=now)
    assert observed["etf_tick_grid_near_bucket"]=="TWO_TO_FOUR"
    assert observed["etf_tick_research_shadow_compatible_bucket"]=="TWO_TO_FOUR"
    assert "9999999" not in str(observed)
    corrupt={**raw,"quarantine_ohlc_gap_evidence":{
        **raw["quarantine_ohlc_gap_evidence"],
        "ETF_LATTICE_QUANTIZE_WOULD_ENCLOSE_BODY":5,
    }}
    bad=audit.summarize_private_frame_progress(corrupt,timeframe="15m",now_utc=now)
    assert bad["etf_tick_research_shadow_compatible_bucket"]=="UNKNOWN"

def test_ec2_independent_cn_source_parity_emits_only_fixed_buckets():
    from datetime import datetime,timezone
    from scripts.audit_cn_tickflow_research_runtime import shadow_compare_eastmoney
    now=datetime(2026,10,13,7,15,tzinfo=timezone.utc)
    labels=["2026-10-09 09:45","2026-10-09 10:00",
            "2026-10-09 10:15","2026-10-09 10:30"]
    def row(label,delta=0.0):
        return dict(label=label,open=1.25+delta,high=1.26+delta,
                    low=1.24+delta,close=1.255+delta)
    tf={"symbols":{"159611.SZ":{"15m":{"rows":[row(x) for x in labels]}}}}
    ref={"schema":"stock_razor_cn_eastmoney_observation_v1",
        "research_only":True,"radar_admission":"BLOCKED","live_trade":False,
        "emitted_at_utc":now.isoformat(),
        "symbols":{"159611":{"timeframes":{"15m":{
            "status":"PASS","provider_used":"eastmoney","adjustment":"NONE",
            "timestamp_semantic":"BAR_END",
            "timestamp_qualification":{"status":"PASS","timestamp_semantic":"BAR_END"},
            "rows":[{**row(x,0.0003),"quality_flags":[]} for x in labels],
        }}}}}
    result=shadow_compare_eastmoney(tf,ref,now_utc=now)
    one=result["159611_SZ_15m"]
    assert one["status"]=="OBSERVED_NOT_ADMITTED"
    assert one["lineage"]=="EASTMONEY"
    assert one["overlap_bucket"]=="TWO_TO_FOUR"
    assert one["max_price_difference_ticks"]=="UNDER_HALF_TICK"
    assert "2026" not in str(result) and "1.255" not in str(result)
    bad={**ref,"research_only":False}
    reject=shadow_compare_eastmoney(tf,bad,now_utc=now)
    assert reject["159611_SZ_15m"]["status"]=="INVALID_REFERENCE"
    corrupt={**ref,"symbols":{"159611":{"timeframes":{"15m":{
        **ref["symbols"]["159611"]["timeframes"]["15m"],
        "timestamp_semantic":"UNKNOWN",
    }}}}}
    assert shadow_compare_eastmoney(tf,corrupt,now_utc=now)[
        "159611_SZ_15m"]["status"]=="UNQUALIFIED_REFERENCE_GRID"

def test_independent_price_reference_naive_clock_must_fail_closed():
    from datetime import datetime,timezone
    from scripts.audit_cn_tickflow_research_runtime import shadow_compare_eastmoney
    now=datetime(2026,10,13,7,15,tzinfo=timezone.utc)
    src={"schema":"stock_razor_cn_eastmoney_observation_v1",
         "research_only":True,"radar_admission":"BLOCKED",
         "live_trade":False,"emitted_at_utc":"2026-10-13T07:15:00",
         "symbols":{}}
    result=shadow_compare_eastmoney({"symbols":{}},src,now_utc=now)
    assert all(item["status"]=="INVALID_REFERENCE" for item in result.values())
    assert all(item["max_price_difference_ticks"]=="UNKNOWN"
               for item in result.values())

def test_qualified_tencent_crosscheck_is_research_only_enum_counts():
    from scripts.audit_cn_tickflow_research_runtime import compare_tencent_qualified_price_rows
    labels=["2026-10-09 09:45","2026-10-09 10:00",
            "2026-10-09 10:15","2026-10-09 10:30"]
    def row(l,d=0):
        return dict(label=l,open=1.2+d,high=1.3+d,
                    low=1.1+d,close=1.25+d)
    tick=[row(t) for t in labels]
    reference=[{**row(t,0.0004),"quality_flags":[]} for t in labels]
    for i in range(44):
        reference.append({**row(f"2026-10-{10+(i%4):02d} {9+(i%8):02d}:45"),
                          "quality_flags":[]})
    result=compare_tencent_qualified_price_rows(
        tick,reference,qualification_pass=True)
    assert result["status"]=="OBSERVED_NOT_ADMITTED"
    assert result["overlap_bucket"]=="TWO_TO_FOUR"
    assert result["max_ohlc_price_difference_ticks"]=="UNDER_HALF_TICK"
    assert "2026" not in str(result) and "1.25" not in str(result)
    refused=compare_tencent_qualified_price_rows(
        tick,reference,qualification_pass=False)
    assert refused["status"]=="UNQUALIFIED_GRID"
    assert refused["max_ohlc_price_difference_ticks"]=="UNKNOWN"


def test_tencent_shadow_never_calls_provider_without_private_tickflow_cache(monkeypatch):
    from scripts.audit_cn_tickflow_research_runtime import sample_tencent_qualified_parity
    monkeypatch.setattr("scripts.audit_cn_tickflow_research_runtime.WORKER_FILE",
                        __import__("pathlib").Path("/missing/no-cache"))
    states=sample_tencent_qualified_parity()
    assert len(states)==4
    assert all(x["status"]=="NO_PRIVATE_TICKFLOW_SNAPSHOT" for x in states.values())

def test_qualified_tencent_price_parity_splits_closed_past_from_latest_day():
    from scripts.audit_cn_tickflow_research_runtime import compare_tencent_qualified_price_rows
    earlier=["2026-10-09 09:45","2026-10-09 10:00",
             "2026-10-09 10:15","2026-10-09 10:30"]
    today=["2026-10-13 09:45","2026-10-13 10:00",
           "2026-10-13 10:15","2026-10-13 10:30"]
    def base(t):
        return {"label":t,"open":1.25,"high":1.26,"low":1.24,"close":1.255}
    tick=[base(x) for x in earlier+today]
    reference=[
        {**base(x),"high":1.2603,"quality_flags":[]} for x in earlier
    ]+[
        {**base(x),"high":1.265,"quality_flags":[]} for x in today
    ]+[
        {**base("2026-10-07 09:45"),"quality_flags":[]}
        for _ in range(40)
    ]
    d=compare_tencent_qualified_price_rows(
        tick,reference,qualification_pass=True,session_date="2026-10-13"
    )
    assert d["status"]=="OBSERVED_NOT_ADMITTED"
    assert d["max_ohlc_price_difference_ticks"]=="OVER_TWO_TICKS"
    assert d["earlier_session_agreement"]=="ALL_WITHIN_ONE_TICK"
    assert d["same_session_agreement"]=="NONE_WITHIN_ONE_TICK"
    assert d["earlier_session_overlap_bucket"]=="TWO_TO_FOUR"
    assert d["same_session_overlap_bucket"]=="TWO_TO_FOUR"
    assert "2026" not in str(d) and "1.265" not in str(d)

def test_qualified_tencent_session_disagreement_driver_and_clock_are_private_enums():
    from scripts.audit_cn_tickflow_research_runtime import compare_tencent_qualified_price_rows
    labels=["2026-10-13 09:45","2026-10-13 10:00",
            "2026-10-13 13:15","2026-10-13 14:45","2026-10-13 15:00"]
    def candle(t):
        return dict(label=t,open=1.20,high=1.23,low=1.19,close=1.21)
    tick=[candle(x) for x in labels]
    reference=[{**candle(x),"quality_flags":[]} for x in labels]
    reference[3]["high"]=1.24
    reference[4]["high"]=1.24
    reference.extend([{**candle("2026-10-09 09:45"),"quality_flags":[]}
                     for _ in range(48)])
    result=compare_tencent_qualified_price_rows(tick,reference,
        qualification_pass=True,session_date="2026-10-13")
    assert result["same_session_disagreement_driver"]=="HIGH"
    assert result["same_session_disagreement_phase"]=="CLOSING"
    assert result["same_session_disagreement_bucket"]=="TWO_TO_FOUR"
    assert result["same_session_agreement"]=="GE50_PCT"
    assert "1.24" not in str(result) and "14:45" not in str(result)
    ref2=[{**candle(x),"quality_flags":[]} for x in labels]
    ref2.extend(reference[5:])
    okay=compare_tencent_qualified_price_rows(tick,ref2,
        qualification_pass=True,session_date="2026-10-13")
    assert okay["same_session_disagreement_driver"]=="NONE"
    assert okay["same_session_disagreement_phase"]=="NONE"
    assert okay["same_session_disagreement_bucket"]=="ZERO"
    invalid=compare_tencent_qualified_price_rows(tick,ref2,
        qualification_pass=False,session_date="2026-10-13")
    assert invalid["same_session_disagreement_driver"]=="UNKNOWN"


def test_cloud_audit_projects_only_safe_cache_reasons_and_main_sha_match():
    from pathlib import Path
    from scripts.audit_cn_tickflow_research_runtime import safe_cache_rejection_reason
    assert safe_cache_rejection_reason("CACHE_SCHEMA_MISMATCH")=="CACHE_SCHEMA_MISMATCH"
    assert safe_cache_rejection_reason("CACHE_PROVIDER_MISMATCH")=="CACHE_PROVIDER_MISMATCH"
    assert safe_cache_rejection_reason("API_KEY=secret")=="UNKNOWN"
    assert safe_cache_rejection_reason(None)=="UNKNOWN"
    root=Path(__file__).resolve().parent.parent
    source=(root/"scripts/audit_cn_tickflow_research_runtime.py").read_text(encoding="utf-8")
    workflow=(root/".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    assert "STOCK_RAZOR_EXPECTED_MAIN_SHA" in source
    assert "worker_source_matches_main" in source and "mcp_source_matches_main" in source
    assert "worker_source_matches_main" in workflow and "mcp_source_matches_main" in workflow
    assert "historical_cache_rejection_reason" in workflow
    assert "CACHE_SCHEMA_MISMATCH" in source


def test_failure_reason_projection_accepts_only_fixed_row_count_enums():
    from scripts.audit_cn_tickflow_research_runtime import safe_failure_reason
    assert safe_failure_reason("ROW_COUNT_BELOW_MIN")=="ROW_COUNT_BELOW_MIN"
    assert safe_failure_reason("ROW_COUNT_ABOVE_MAX")=="ROW_COUNT_ABOVE_MAX"
    assert safe_failure_reason("ROW_COUNT_OUT_OF_BOUNDS")=="ROW_COUNT_OUT_OF_BOUNDS"
    assert safe_failure_reason("credential=secret")=="UNKNOWN"
