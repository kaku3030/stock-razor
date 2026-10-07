import json

from src.services.stock_radar_v2.daily_history_reader import (
    load_futu_us_daily_history_frames,
)


SHA = "a" * 40


def _payload(*, safe=True, status="PASS", repo_sha=SHA):
    rows = []
    for index in range(120):
        day = f"2026-{4 + index // 28:02d}-{1 + index % 28:02d}"
        rows.append(
            {
                "date": day,
                "open": 100 + index,
                "high": 102 + index,
                "low": 99 + index,
                "close": 101 + index,
                "volume": 1000 + index,
                "amount": 100000 + index,
                "provider": "futu",
                "feed": "opend",
                "quality_flags": ["HISTORICAL_QUERY"],
            }
        )
    return {
        "schema": "stock_razor_futu_us_daily_history_v1",
        "repo_sha": repo_sha,
        "runtime_instance_id": "runtime-1",
        "emitted_at_utc": "2026-10-07T08:00:00+00:00",
        "status": status,
        "symbols": {
            "US.AMD": {
                "status": "PASS",
                "symbol": "US.AMD",
                "row_count": 120,
                "latest_date": rows[-1]["date"],
                "rows": rows,
                "required_rows": 120,
                "cutoff_market_date": "2026-10-07",
                "completed_prior_session_only": True,
                "historical_query": True,
                "currentness_proven": False,
                "bar_closure_promotion_authorized": False,
                "radar_admission": "BLOCKED",
                "live_trade": False,
                "reasons": [],
            }
        },
        "required_rows": 120,
        "lookback_calendar_days": 260,
        "provider": "futu",
        "feed": "opend",
        "same_opend_context_required": True,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "research_only": True if safe else False,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def _write(tmp_path, payload):
    path = tmp_path / "daily-history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_reader_returns_daily_dataframe_and_safe_diagnostics(tmp_path):
    frames, diagnostics = load_futu_us_daily_history_frames(
        _write(tmp_path, _payload()),
        expected_repo_sha=SHA,
    )

    assert diagnostics["status"] == "PASS"
    assert diagnostics["radar_admission"] == "BLOCKED"
    assert diagnostics["live_trade"] is False
    assert set(frames) == {"US.AMD"}
    frame = frames["US.AMD"]
    assert len(frame) == 120
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert float(frame.iloc[-1]["close"]) > 0


def test_reader_rejects_source_sha_mismatch(tmp_path):
    frames, diagnostics = load_futu_us_daily_history_frames(
        _write(tmp_path, _payload(repo_sha="b" * 40)),
        expected_repo_sha=SHA,
    )
    assert frames == {}
    assert diagnostics["status"] == "BLOCKED"
    assert diagnostics["reason"] == "SOURCE_REPO_SHA_MISMATCH"


def test_reader_rejects_safety_contract_drift(tmp_path):
    frames, diagnostics = load_futu_us_daily_history_frames(
        _write(tmp_path, _payload(safe=False)),
        expected_repo_sha=SHA,
    )
    assert frames == {}
    assert diagnostics["reason"] == "SAFETY_CONTRACT_VIOLATION"
    assert diagnostics["radar_admission"] == "BLOCKED"
    assert diagnostics["live_trade"] is False


def test_reader_rejects_non_pass_source(tmp_path):
    frames, diagnostics = load_futu_us_daily_history_frames(
        _write(tmp_path, _payload(status="PARTIAL")),
        expected_repo_sha=SHA,
    )
    assert frames == {}
    assert diagnostics["reason"] == "SOURCE_STATUS_NOT_PASS"


def test_reader_rejects_too_few_rows(tmp_path):
    payload = _payload()
    payload["symbols"]["US.AMD"]["rows"] = payload["symbols"]["US.AMD"]["rows"][:59]
    frames, diagnostics = load_futu_us_daily_history_frames(
        _write(tmp_path, payload),
        expected_repo_sha=SHA,
    )
    assert frames == {}
    assert diagnostics["reason"] == "INSUFFICIENT_DAILY_ROWS:US.AMD"
