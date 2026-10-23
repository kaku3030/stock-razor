"""Real cache validation -> existing technical analyzer -> existing worker."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data_provider.cn_tickflow_research_cache import SCHEMA, SYMBOLS, normalize_bars
from src.services.stock_radar_v2.tickflow_observation_analysis import (
    evaluate_tickflow_observation_payload, validate_tickflow_source_clock,
)

NOW = datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)


def observation(now=NOW):
    frames = {}
    for period, clocks in (("15m", ("09:45", "10:00", "10:15", "10:30",
                           "10:45", "11:00", "11:15", "11:30", "13:15",
                           "13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00")),
                           ("60m", ("10:30", "11:30", "14:00", "15:00")),
                           ("1d", ("00:00",))):
        stamps = [datetime.fromisoformat(str(day.date()) + "T" + clock).replace(
            tzinfo=ZoneInfo("Asia/Shanghai"))
            for day in pd.bdate_range(end="2026-10-16", periods=24 if period != "1d" else 40)
            for clock in clocks]
        if period in ("15m", "60m"):
            stamps = stamps[-(96 if period == "15m" else 24):]
        rows = [dict(timestamp=int(stamp.timestamp()) * 1000, open=1.5,
                     high=1.7, low=1.3, close=1.6, volume=1000, amount=1600)
                for stamp in stamps]
        frames[period] = {"rows": normalize_bars(pd.DataFrame(rows), period, now_utc=now),
                          "closure": "NOT_VERIFIED", "currentness": "UNPROVEN"}
    return {"schema": SCHEMA, "provider": "TICKFLOW_PREMIUM", "repo_sha": "a" * 40,
            "observed_at_utc": now.isoformat(), "sequence": 1,
            "status": "PASS_RESEARCH_ONLY", "symbols": {s: copy.deepcopy(frames) for s in SYMBOLS},
            "source_arbiter_admission": "BLOCKED", "radar_admission": "BLOCKED",
            "canonical_write_authorized": False, "can_confirm_signal": False,
            "research_only": True, "live_trade": False}


@pytest.mark.parametrize("short_history", [False, True])
def test_real_cache_to_radar_retains_provenance_and_partial_bars(monkeypatch, short_history):
    source = observation()
    if short_history:
        # Actual first AWS cache: requested depth is not returned coverage.
        for frames in source["symbols"].values():
            frames["60m"]["rows"] = frames["60m"]["rows"][-4:]
            frames["15m"]["rows"] = frames["15m"]["rows"][-16:]
    original = copy.deepcopy(source)
    def no_io(*args, **kwargs):
        raise AssertionError("cache adapter must not perform I/O")
    monkeypatch.setattr("builtins.open", no_io)
    result = evaluate_tickflow_observation_payload(source, now_utc=NOW)
    assert result["status"] == "PASS"
    assert source == original
    assert result["source_sequence"] == 1
    assert result["source_runtime_instance_id"] == "NOT_VERIFIED"
    assert result["provider_lineages"] == ["tickflow"]
    assert result["intraday_currentness_proven"] is False
    assert set(result["research_state_symbols"]) == {s.split(".")[0] for s in SYMBOLS}
    for item in result["symbols"].values():
        assert item["signal_permission"] == "record_only"
        assert item["intraday_timestamp_semantics_proven"] is False
        for frame in item["frame_provenance"].values():
            assert frame["provider_used"] == "TICKFLOW_PREMIUM"
            assert frame["volume_unit"] == "NOT_VERIFIED"
            assert frame["bar_finality"] == "NOT_VERIFIED"
        assert item["technical"]["hourly"]["quality"]["is_partial_bar"] is True
        assert item["technical"]["intraday"]["quality"]["is_partial_bar"] is True
        if short_history:
            assert "1h_insufficient_bars" in item["technical"]["hourly"]["quality"]["warnings"]
            assert "tickflow_indicator_history_insufficient" in item["technical"]["risk_flags"]


@pytest.mark.parametrize("case", ["unsafe", "provider", "schema", "sequence", "stale",
    "future", "missing_frame", "nan", "duplicate", "closure", "naive"])
def test_bad_source_never_becomes_analysis(case):
    source = observation()
    if case == "unsafe": source["live_trade"] = True
    elif case == "provider": source["provider"] = "tencent"
    elif case == "schema": source["schema"] = "other"
    elif case == "sequence": source["sequence"] = True
    elif case in {"stale", "future", "naive"}:
        stamp = NOW + timedelta(seconds=1 if case == "future" else -1081)
        source["observed_at_utc"] = (stamp.replace(tzinfo=None) if case == "naive" else stamp).isoformat()
    elif case == "missing_frame": del source["symbols"][SYMBOLS[0]]["1d"]
    elif case == "nan": source["symbols"][SYMBOLS[0]]["15m"]["rows"][0]["close"] = float("nan")
    elif case == "duplicate":
        rows = source["symbols"][SYMBOLS[0]]["15m"]["rows"]
        rows[1]["label"] = rows[0]["label"]
    elif case == "closure": source["symbols"][SYMBOLS[0]]["15m"]["closure"] = "PROVEN"
    with pytest.raises((ValueError, KeyError)):
        evaluate_tickflow_observation_payload(source, now_utc=NOW)


def test_unchanged_source_expires_without_reanalysis():
    source = observation()
    validate_tickflow_source_clock(source, NOW)
    with pytest.raises(ValueError):
        validate_tickflow_source_clock(source, NOW + timedelta(seconds=1081))


def test_existing_vendor_float_policy_is_preserved_without_price_mutation():
    source = observation()
    row = source["symbols"][SYMBOLS[0]]["15m"]["rows"][0]
    row.update(open=1.5, close=1.5, high=1.5 - 1e-14,
               ohlc_validation="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY")
    original = copy.deepcopy(source)
    result = evaluate_tickflow_observation_payload(source, now_utc=NOW)
    assert result["status"] == "PASS"
    assert "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY" in result["symbols"]["159611"]["frame_provenance"]["15m"]["analysis_warnings"]
    assert source == original
    row["high"] = 1.49
    with pytest.raises(ValueError):
        evaluate_tickflow_observation_payload(source, now_utc=NOW)


def test_same_day_daily_label_is_quarantined():
    now = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
    result = evaluate_tickflow_observation_payload(observation(now), now_utc=now)
    for item in result["symbols"].values():
        daily = item["frame_provenance"]["1d"]
        assert daily["row_count"] == 40
        assert daily["analysis_row_count"] == 39
        assert "CURRENT_OR_FUTURE_DAILY_DATE_EXCLUDED" in daily["analysis_warnings"]


@pytest.mark.parametrize("case,passes", [("valid", True), ("wrong_source", False),
    ("wrong_sequence", False), ("wrong_policy", False), ("unsafe", False),
    ("false_closed", False)])
def test_actual_deployment_verifier_independently_reads_source(tmp_path, case, passes):
    source = observation(datetime.now(timezone.utc))
    evaluation = evaluate_tickflow_observation_payload(source, now_utc=datetime.now(timezone.utc))
    heartbeat = {"type": "cn_radar_research_heartbeat", "worker_repo_sha": "b" * 40,
        "source_repo_sha": source["repo_sha"], "source_sequence": source["sequence"],
        "source_emitted_at_utc": source["observed_at_utc"], "source_age_seconds": 0.1,
        "sequence": 1, "poll_status": "UNCHANGED", "research_only": True,
        "can_confirm_signal": False, "radar_admission": "BLOCKED", "live_trade": False,
        "radar_analysis_performed": False, "radar_analysis_latency_ms": None,
        "data_to_radar_latency_ms": None, "evaluation": evaluation}
    if case == "wrong_source": source["repo_sha"] = "c" * 40
    elif case == "wrong_sequence": source["sequence"] += 1
    elif case == "wrong_policy": evaluation["provider_policy"] = "EASTMONEY_PRIMARY_TENCENT_FALLBACK"
    elif case == "unsafe": heartbeat["live_trade"] = True
    elif case == "false_closed":
        evaluation["symbols"]["159611"]["technical"]["hourly"]["quality"]["is_partial_bar"] = False
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source))
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps(heartbeat))
    code = Path("ops/aws/verify_cn_radar_worker.sh").read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    code = code.replace("/run/stock-razor-cn-tickflow/latest-research-observation.json", source_path.as_posix())
    result = subprocess.run([sys.executable, "-", str(status_path), "b" * 40, "tickflow"],
        input=code, text=True, capture_output=True, timeout=5)
    assert (result.returncode == 0) is passes, result.stderr


@pytest.mark.parametrize("second", ["unchanged", "unsafe_replacement"])
def test_actual_installed_worker_loop(tmp_path, monkeypatch, capsys, second):
    import time
    source = tmp_path / "source.json"
    source.write_text(json.dumps(observation(datetime.now(timezone.utc))))
    status = tmp_path / "status.json"
    for name, value in {"STOCK_RAZOR_WORKER_REPO_SHA": "b" * 40,
                        "STOCK_RAZOR_CN_OBSERVATION_PATH": str(source),
                        "STOCK_RAZOR_CN_RADAR_STATUS_PATH": str(status),
                        "STOCK_RAZOR_CN_RADAR_SOURCE_PROVIDER": "tickflow"}.items():
        monkeypatch.setenv(name, value)
    class StopLoop(Exception): pass
    count = 0
    def next_poll(seconds):
        nonlocal count
        count += 1
        if count == 2: raise StopLoop()
        if second == "unsafe_replacement":
            payload = json.loads(source.read_text())
            payload["live_trade"] = True
            source.write_text(json.dumps(payload))
    monkeypatch.setattr(time, "sleep", next_poll)
    code = Path("ops/aws/install_cn_radar_worker.sh").read_text().split(
        'cat >"$INSTALL_ROOT/run.py" <<\'PY\'\n', 1)[1].split("\nPY\n", 1)[0]
    with pytest.raises(StopLoop):
        exec(compile(code, "installed-cn-worker", "exec"), {})
    payload = json.loads(status.read_text())
    assert payload["worker_repo_sha"] == "b" * 40
    assert payload["source_repo_sha"] == "a" * 40
    assert payload["radar_admission"] == "BLOCKED"
    if second == "unchanged":
        assert payload["poll_status"] == "UNCHANGED"
        assert payload["evaluation"]["provider_lineages"] == ["tickflow"]
        assert payload["radar_analysis_performed"] is False
    else:
        assert payload["poll_status"] == "BLOCKED"
        assert payload["evaluation"] is None



def test_today_vendor_float_reaches_only_session_progress_research():
    from data_provider.cn_tickflow_research_cache import _LABEL_END
    now=datetime(2026,10,16,4,0,tzinfo=timezone.utc)  # Shanghai lunch
    source=observation(now)
    for frames in source["symbols"].values():
        for period in ("15m","60m"):
            prior=[r for r in frames[period]["rows"] if not r["label"].startswith("2026-10-16")]
            today=[dict(label="2026-10-16 "+clock,open=1.5,high=1.7,
                        low=1.3,close=1.6,volume=1000,amount=1600,
                        amount_availability="PRESENT_UNVERIFIED",is_partial_bar=True,
                        bar_finality="NOT_VERIFIED",ohlc_validation="STRICT")
                   for clock in sorted(_LABEL_END[period]) if clock<="11:30"]
            if period=="15m":
                today[0]["high"]=1.599999999999
                today[0]["ohlc_validation"]="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
            frames[period]["rows"]=(prior+today)[-(96 if period=="15m" else 24):]
    result=evaluate_tickflow_observation_payload(source,now_utc=now)
    assert result["status"] == "PASS"
    assert result["intraday_currentness_proven"] is False
    assert result["can_confirm_signal"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert all(item["signal_permission"]=="record_only" for item in result["symbols"].values())
    # A missing due boundary still fails; no retry in historical mode hides it.
    source["symbols"][SYMBOLS[0]]["15m"]["rows"]=[r for r in source["symbols"][SYMBOLS[0]]["15m"]["rows"] if r["label"]!="2026-10-16 10:00"]
    with pytest.raises(ValueError):
        evaluate_tickflow_observation_payload(source,now_utc=now)
