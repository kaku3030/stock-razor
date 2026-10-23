"""5m audit evidence is fixed-enum and contains no private OHLC fields."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from scripts.audit_cn_tickflow_research_runtime import summarize_private_frame_progress

CN = ZoneInfo("Asia/Shanghai")
N = datetime(2026, 10, 15, 3, 35, tzinfo=timezone.utc)


def _fixture():
    date="2026-10-15"
    times=[*range(575,691,5),*range(785,901,5)][:24]
    rows=[{"label":f"{date} {m//60:02d}:{m%60:02d}",
           "open":1.5, "high":1.51, "low":1.49, "close":1.505,
           "volume":100, "amount":100, "is_partial_bar":True,
           "bar_finality":"NOT_VERIFIED", "ohlc_validation":"STRICT",
           "amount_availability":"PRESENT_UNVERIFIED"} for m in times]
    return {"rows":rows, "quarantine_reason_counts":{},
            "quarantine_ohlc_gap_evidence":{},
            "quarantined_unverified_rows_count":0}


def test_5m_sanitized_grid_complete_and_redacted():
    frame=_fixture()
    d=summarize_private_frame_progress(frame,timeframe="5m",now_utc=N)
    assert d["last_due_grid"]=="MATCHED_DUE_LABEL"
    assert d["due_grid_continuity"]=="ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY"
    assert d["retained_bar_count_bucket"]=="FOUR_TO_24"
    assert "rows" not in d and "1.505" not in str(d) and "2026-10-15" not in str(d)


def test_5m_missing_middle_label_detected_without_timestamp():
    frame=_fixture()
    frame["rows"]=[r for r in frame["rows"] if not r["label"].endswith("10:00")]
    d=summarize_private_frame_progress(frame,timeframe="5m",now_utc=N)
    assert d["due_grid_continuity"]=="ONE_DUE_LABEL_MISSING"
    assert d["last_due_grid"]=="MATCHED_DUE_LABEL"
    assert "10:00" not in str(d)


def test_5m_extra_day_bounded_144_rows():
    frame=_fixture()
    prior=[]
    for day in ("2026-10-13","2026-10-14"):
        for m in [*range(575,691,5),*range(785,901,5)]:
            prior.append({**frame["rows"][0],
                          "label":f"{day} {m//60:02d}:{m%60:02d}"})
    frame["rows"]=prior+frame["rows"]
    d=summarize_private_frame_progress(frame,timeframe="5m",now_utc=N)
    assert d["retained_bar_count_bucket"]=="97_TO_144"
    assert d["due_grid_continuity"]=="ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY"


def test_github_sanitized_projection_includes_five_minute_fixed_enums():
    from pathlib import Path
    workflow=(Path(__file__).resolve().parents[1]/
             ".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    assert '"159209_SZ_1m","159209_SZ_5m","159209_SZ_15m","159209_SZ_60m"' in workflow
    assert '"supplemental_5m_reader":{p:compact_reader(d["after"]["supplemental_5m_reader"].get(p,{}))' in workflow
    assert 'set(frame_map).issubset(historical_periods)' in workflow
    assert 'allowed_rows=("UNKNOWN","FOUR_TO_24","25_TO_96","97_TO_144","145_TO_240")' in workflow
