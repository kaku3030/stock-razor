"""Audit missing TickFlow cache without leaking file or provider details."""
from pathlib import Path

import pytest

import scripts.audit_cn_tickflow_research_runtime as audit


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (None, "FILE_MISSING"),
        ("", "FILE_SIZE_INVALID"),
        ("not-json", "JSON_INVALID"),
        ("{}", "SCHEMA_INVALID"),
    ],
)
def test_missing_cache_fails_closed_with_sanitized_reason(
    tmp_path: Path, monkeypatch, content, expected,
):
    cache = tmp_path / "latest-research-observation.json"
    if content is not None:
        cache.write_text(content, encoding="utf-8")
    monkeypatch.setattr(audit, "WORKER_FILE", cache)
    monkeypatch.setattr(audit, "active", lambda _unit: True)

    result = audit.sample()
    assert result["status"] == "NO_VALID_CACHE"
    assert result["cache_unavailable_reason"] == expected
    assert result["repo_sha_match"] is False
    assert result["sequence"] is None
    assert result["all_four_historical_requests_ok"] is False
    assert result["all_four_readonly_requests_ok"] is False
    assert result["mcp_cache_consumer"] == "NOT_VERIFIED"


def test_oversized_private_cache_never_read_or_exported(tmp_path, monkeypatch):
    cache = tmp_path / "latest-research-observation.json"
    cache.write_bytes(b"Z" * (audit.MAX_FILE_BYTES + 1))
    monkeypatch.setattr(audit, "WORKER_FILE", cache)
    monkeypatch.setattr(audit, "active", lambda _unit: True)
    result = audit.sample()
    assert result["status"] == "NO_VALID_CACHE"
    assert result["cache_unavailable_reason"] == "FILE_SIZE_INVALID"
    # An isolated character can appear in safe enum names (e.g. SIZE).
    # Only the full unique raw fixture payload must remain undisclosed.
    assert "Z" * 64 not in str(result)


def test_public_workflow_requires_fixed_failure_enum_and_serialized_deploy():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / ".github/workflows/audit-cn-tickflow-live-research.yml"
    ).read_text(encoding="utf-8")
    assert 'keys=("status","cache_unavailable_reason",' in source
    assert 'assert d[when].get("cache_unavailable_reason") in cache_absence' in source
    assert 'group: cn-tickflow-research-worker' in source
    assert "cancel-in-progress: false" in source
    assert "RADAR_ADMISSION=BLOCKED" in source
    assert "LIVE_TRADE=NO" in source


def test_aws_audit_accepts_same_bounded_size_as_private_writer_and_reader():
    from data_provider.cn_tickflow_research_cache import MAX_BYTES

    # Auditor used to impose a smaller 150 KB limit and falsely report
    # NO_VALID_CACHE for a legitimate bounded private snapshot.
    assert audit.MAX_FILE_BYTES == MAX_BYTES == 64_000_000


@pytest.mark.parametrize("symbol_index", [0, 1, 2, 3, 199])
@pytest.mark.parametrize("period", ["1M", "15M", "60M", "5M", "1D"])
@pytest.mark.parametrize("action", ["FETCH", "NORMALIZE"])
def test_worker_all_requested_failure_stages_are_safely_classified(
    symbol_index, period, action,
):
    # AWS worker include_supplemental=True requests all five timeframes;
    # 5m/1d outages must not disappear into UNKNOWN in the public audit.
    stage = f"S{symbol_index}_{period}_{action}"
    assert audit.safe_failure_stage(stage) == stage


@pytest.mark.parametrize("stage", ["S4_WS_SUMMARY", "S4_CACHE_PUBLISH"])
def test_worker_publish_and_websocket_failure_stages_are_safe(stage):
    assert audit.safe_failure_stage(stage) == stage


@pytest.mark.parametrize("malicious", [
    None, 0, True, {}, "S0_2M_FETCH", "S200_5M_FETCH",
    "S0_5M_FETCH\\nAPI_KEY=DO_NOT_ECHO", "S1_1D_NORMALIZE_SECRET",
])
def test_worker_failure_stage_projection_is_enum_only(malicious):
    assert audit.safe_failure_stage(malicious) == "UNKNOWN"
    assert "DO_NOT_ECHO" not in audit.safe_failure_stage(malicious)


@pytest.mark.parametrize(("record", "expected"), [
    ("TICKFLOW_RESEARCH_BOOT=BLOCKED:RuntimeError", "BOOT_BLOCKED"),
    ("TICKFLOW_RESEARCH_POLL=BLOCKED:RateLimitError", "POLL_BLOCKED"),
    ("TICKFLOW_RESEARCH_POLL=RESEARCH_ONLY_PASS", "POLL_RESEARCH_ONLY_PASS"),
    ("provider_error=API_KEY_SECRET_SHOULD_NEVER_LEAVE", "NO_RECENT_LIFECYCLE_MARKER"),
])
def test_worker_journal_evidence_never_exports_raw_log(monkeypatch, record, expected):
    import subprocess
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, stdout="private_api_key=KEEP_PRIVATE\n" + record,
            stderr="confidential provider stack",
        )

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    state = audit.safe_worker_journal_observation()
    assert state == expected
    assert "KEEP_PRIVATE" not in state
    assert "confidential" not in state
    assert calls[0][0][0] == "journalctl"
    assert calls[0][1]["timeout"] == 5
    assert calls[0][1]["capture_output"] is True


def test_worker_journal_unavailable_fails_closed(monkeypatch):
    import subprocess

    monkeypatch.setattr(
        audit.subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="SECRET"),
    )
    assert audit.safe_worker_journal_observation() == "JOURNAL_UNAVAILABLE"


def test_public_tickflow_workflow_restricts_journal_projection_to_enums():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/audit-cn-tickflow-live-research.yml").read_text()
    assert '"worker_journal_observation"' in workflow
    assert 'assert d[when].get("worker_journal_observation") in worker_journal' in workflow
    assert '"BOOT_BLOCKED","POLL_BLOCKED","POLL_RESEARCH_ONLY_PASS"' in workflow
    assert "StandardErrorContent" not in workflow


def test_writer_preflights_reader_byte_bound_and_preserves_existing_cache(tmp_path):
    from data_provider.cn_tickflow_research_cache import atomic_publish, MAX_BYTES

    path = tmp_path / "private-cache.json"
    atomic_publish(str(path), {"status": "BLOCKED", "source": "research"})
    original = path.read_bytes()
    oversized = {"secret_in_private_payload": "V" * MAX_BYTES}
    with pytest.raises(ValueError, match="bounded bytes"):
        atomic_publish(str(path), oversized)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
    assert "V" * 64 not in path.read_text(encoding="utf-8")


def test_private_tickflow_writer_enforces_same_limit_as_audit_and_reader():
    from data_provider.cn_tickflow_research_cache import atomic_publish, MAX_BYTES
    import inspect

    source = inspect.getsource(atomic_publish)
    assert audit.MAX_FILE_BYTES == MAX_BYTES == 64_000_000
    assert 'len(encoded.encode("utf-8"))>MAX_BYTES' in source
    assert source.index("len(encoded.encode") < source.index("parent.mkdir")


def test_cn_15m_morning_first_close_has_90s_grace_and_no_false_live_admission():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    cn = ZoneInfo("Asia/Shanghai")
    previous = [
        "2026-10-14 09:45", "2026-10-14 10:00",
        "2026-10-14 10:15", "2026-10-14 10:30",
    ]
    def observe(clock, today):
        frame = {
            "rows": [
                {"label": label, "close": 999999.123}
                for label in previous + today
            ],
            "quarantined_unverified_rows_count": 0,
            "quarantine_reason_counts": {},
        }
        return audit.summarize_private_frame_progress(
            frame, timeframe="15m",
            now_utc=datetime(2026, 10, 15, *clock, tzinfo=cn),
        )

    before_close = observe((9, 44), [])
    assert before_close["due_grid_continuity"] == "NO_SESSION_GRID_DUE"
    # The provider's next bar-end label can be forming for another 90s.
    within_grace = observe((9, 45, 30), [])
    assert within_grace["due_grid_continuity"] == "NO_SESSION_GRID_DUE"
    due_without_row = observe((9, 46, 30), [])
    assert due_without_row["due_grid_continuity"] == "NO_SAME_DAY_RETAINED_BAR"
    with_first_row = observe((9, 46, 30), ["2026-10-15 09:45"])
    assert with_first_row["due_grid_continuity"] == "ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY"
    assert "999999" not in str(with_first_row)
    assert "2026-10-15" not in str(with_first_row)

    # Previous audit checked only the latest label, missing the 09:45 gap.
    skipped_first = observe((10, 2), ["2026-10-15 10:00"])
    assert skipped_first["last_due_grid"] == "MATCHED_DUE_LABEL"
    assert skipped_first["due_grid_continuity"] == "ONE_DUE_LABEL_MISSING"
    complete = observe((10, 2), ["2026-10-15 09:45", "2026-10-15 10:00"])
    assert complete["due_grid_continuity"] == "ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY"


def test_cn_60m_first_close_due_after_90s_and_missing_prior_hour_detected():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    cn = ZoneInfo("Asia/Shanghai")
    older = [
        {"label": f"2026-10-14 {clock}"}
        for clock in ("10:30", "11:30", "14:00", "15:00")
    ]
    def check(hour, minute, second, todays):
        frame = {
            "rows": older + [{"label": "2026-10-15 " + clock} for clock in todays],
            "quarantined_unverified_rows_count": 0,
        }
        return audit.summarize_private_frame_progress(
            frame, timeframe="60m",
            now_utc=datetime(2026,10,15,hour,minute,second,tzinfo=cn),
        )
    assert check(10,30,30,[])["due_grid_continuity"] == "NO_SESSION_GRID_DUE"
    assert check(10,31,30,["10:30"])["due_grid_continuity"] == "ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY"
    assert check(11,32,0,["11:30"])["due_grid_continuity"] == "ONE_DUE_LABEL_MISSING"
    assert check(11,32,0,["10:30","11:30"])["due_grid_continuity"] == "ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY"
    assert check(11,32,0,["10:30","10:30","11:30"])["due_grid_continuity"] == "INVALID_TODAY_LABEL_GRID"


def test_cloud_audit_accepts_only_fixed_due_grid_continuity_enum():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/audit-cn-tickflow-live-research.yml").read_text()
    assert "allowed_continuity=" in workflow
    assert 'assert _v.get("due_grid_continuity") in allowed_continuity' in workflow
    assert "ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY" in workflow
    assert "RADAR_ADMISSION=BLOCKED" in workflow


def test_cloud_audit_preserves_secondary_ohlc_rejection_without_exposing_prices():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cn = ZoneInfo("Asia/Shanghai")
    frame = {
        "rows": [
            {"label": "2026-10-14 14:00", "close": 998899.123},
            {"label": "2026-10-14 14:15", "close": 998899.123},
            {"label": "2026-10-14 14:30", "close": 998899.123},
            {"label": "2026-10-15 09:45", "close": 998899.123},
        ],
        "quarantined_unverified_rows_count": 3,
        "quarantine_reason_counts": {
            "TODAY_FUTURE_LABEL": 2,
            "TODAY_HIGH_BELOW_BODY": 1,
        },
        "quarantine_ohlc_gap_evidence": {},
    }
    evidence = audit.summarize_private_frame_progress(
        frame, timeframe="15m",
        now_utc=datetime(2026,10,15,10,2,tzinfo=cn),
    )
    assert evidence["last_due_grid"] == "ONE_DUE_BOUNDARY_MISSING"
    assert evidence["dominant_quarantine_reason"] == "TODAY_FUTURE_LABEL"
    assert evidence["quarantine_cause_buckets"] == {
        "TODAY_FUTURE_LABEL": "TWO_TO_FOUR",
        "TODAY_HIGH_BELOW_BODY": "ONE",
    }
    assert "998899" not in repr(evidence)
    assert "2026-10-15" not in repr(evidence)


def test_cloud_audit_rejects_malicious_quarantine_cause_without_leaking():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cn=ZoneInfo("Asia/Shanghai")
    frame={
        "rows": [
            {"label": f"2026-10-14 {clock}"}
            for clock in ("14:00","14:15","14:30","14:45")
        ],
        "quarantined_unverified_rows_count": 1,
        "quarantine_reason_counts": {
            "TODAY_HIGH_BELOW_BODY\\nsecret=DO_NOT_EXPOSE": 1,
        },
    }
    evidence=audit.summarize_private_frame_progress(
        frame,timeframe="15m",
        now_utc=datetime(2026,10,15,10,2,tzinfo=cn),
    )
    assert evidence["quarantine_cause_buckets"] == {}
    assert evidence["dominant_quarantine_reason"] == "UNKNOWN"
    assert "DO_NOT_EXPOSE" not in repr(evidence)


def test_public_workflow_restricts_secondary_quarantine_causes_to_static_enums():
    workflow=(Path(__file__).resolve().parents[1] /
              ".github/workflows/audit-cn-tickflow-live-research.yml").read_text()
    assert 'cause_buckets=_v.get("quarantine_cause_buckets")' in workflow
    assert "name in allowed_cause" in workflow
    assert "bucket in allowed_bucket" in workflow


def test_combined_cloud_audit_and_nonmutating_vendor_float_research_only(tmp_path):
    """Cross-PR acceptance: float-bearing due bar isn't falsely missing,
    but source and trade remain blocked and private price never exported."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    import json
    from data_provider.cn_tickflow_research_cache import (
        build_observation, atomic_publish, read_cn_tickflow_research_data,
    )

    china = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 15, 2, 2, tzinfo=timezone.utc)  # 10:02 CST
    clocks = (
        ("2026-10-14 14:00", "2026-10-14 14:15",
         "2026-10-14 14:30", "2026-10-14 14:45"),
        ("2026-10-15 09:45", "2026-10-15 10:00"),
    )
    def raw_frame(period: str, symbol: str) -> dict:
        if period == "15m":
            labels = [*clocks[0], *clocks[1]]
        else:
            labels = [
                "2026-10-14 10:30", "2026-10-14 11:30",
                "2026-10-14 14:00", "2026-10-14 15:00",
            ]
        count = len(labels)
        high = [1.7] * count
        if symbol == "159611.SZ" and period == "15m":
            high[-2:] = [1.5999999999999994] * 2
        return {
            "timestamp": [
                int(datetime.strptime(label, "%Y-%m-%d %H:%M")
                    .replace(tzinfo=china).timestamp()) * 1000
                for label in labels
            ],
            "open": [1.5] * count, "high": high,
            "low": [1.3] * count, "close": [1.6] * count,
            "volume": [1000] * count, "amount": [1600] * count,
        }

    class Klines:
        def get(self, symbol, *, period, count, as_dataframe, adjust,
                start_time=None,end_time=None):
            assert symbol in ("159611.SZ", "159209.SZ", "512730.SH", "159363.SZ")
            assert period in ("15m", "60m")
            assert count in (96, 24) and as_dataframe is False and adjust == "none"
            return raw_frame(period, symbol)
        def intraday(self,symbol,*,period,count,as_dataframe):
            return self.get(symbol,period=period,count=count,
                            as_dataframe=as_dataframe,adjust="none")
    class Client:
        klines = Klines()

    snap = build_observation(Client(), now_utc=now, repo_sha="f" * 40,
                             sequence=7)
    frame = snap["symbols"]["159611.SZ"]["15m"]
    proof = audit.summarize_private_frame_progress(
        frame, timeframe="15m", now_utc=now,
    )
    assert proof["last_due_grid"] == "MATCHED_DUE_LABEL"
    assert proof["due_grid_continuity"] == "ALL_DUE_LABELS_PRESENT_RESEARCH_ONLY"
    assert proof["quarantine_cause_buckets"] == {}
    assert proof["vendor_float_rows_bucket"] == "TWO_TO_FOUR"
    assert proof["same_session_vendor_float_rows_bucket"] == "TWO_TO_FOUR"
    assert snap["source_arbiter_admission"] == snap["radar_admission"] == "BLOCKED"
    assert snap["can_confirm_signal"] is False
    assert all(bar["bar_finality"] == "NOT_VERIFIED" for bar in frame["rows"])
    assert "1.5999999999999994" not in json.dumps(proof)

    path = tmp_path / "private.json"
    atomic_publish(str(path), snap)
    read = read_cn_tickflow_research_data(
        "159611.SZ", "15m", 2, path=str(path), now_utc=now,
    )
    assert read["status"] == "PASS_RESEARCH_ONLY"
    assert read["ohlc_precision_scope"] == "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert read["tolerated_vendor_float_rows"] == 2
    assert read["currentness"] == "UNPROVEN"
    assert read["bar_finality"] == "NOT_VERIFIED"
    assert read["source_arbiter_admission"] == "BLOCKED"
    assert read["radar_admission"] == "BLOCKED"
    assert read["live_trade"] is False
    assert read["can_confirm_signal"] is False


def test_cloud_precision_projection_enums_are_static_and_price_free():
    root=Path(__file__).resolve().parents[1]
    workflow=(root / ".github/workflows/audit-cn-tickflow-live-research.yml").read_text()
    assert 'assert _v.get("vendor_float_rows_bucket") in allowed_bucket' in workflow
    assert 'assert _v.get("same_session_vendor_float_rows_bucket") in allowed_bucket' in workflow
    assert 'v.get("ohlc_precision_scope") in (' in workflow

    from datetime import datetime
    from zoneinfo import ZoneInfo
    china=ZoneInfo("Asia/Shanghai")
    frame={
        "rows":[
            {"label":f"2026-10-14 {clock}", "ohlc_validation":"STRICT"}
            for clock in ("14:00","14:15","14:30","14:45")
        ]+[{
            "label":"2026-10-15 09:45",
            "ohlc_validation":"SUSPICIOUS_PRICE=12345_DO_NOT_LEAK",
        }],
        "quarantined_unverified_rows_count":0,
        "quarantine_reason_counts":{},
    }
    got=audit.summarize_private_frame_progress(
        frame,timeframe="15m",
        now_utc=datetime(2026,10,15,9,47,tzinfo=china),
    )
    assert got["vendor_float_rows_bucket"]=="UNKNOWN"
    assert got["same_session_vendor_float_rows_bucket"]=="UNKNOWN"
    assert "12345_DO_NOT_LEAK" not in repr(got)


@pytest.mark.parametrize("stage", ["BATCH_1M_FETCH", "BATCH_1D_FETCH", "S199_1M_NORMALIZE"])
def test_expanded_scan_failure_stages_remain_observable(stage):
    assert audit.safe_failure_stage(stage) == stage


@pytest.mark.parametrize("stage", ["S200_1M_FETCH", "BATCH_PRIVATE_FETCH", "BATCH_1M_FETCH api_key=PRIVATE"])
def test_expanded_scan_failure_stages_reject_outside_contract(stage):
    assert audit.safe_failure_stage(stage) == "UNKNOWN"
