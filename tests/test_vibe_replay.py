import csv
import json

from src.services.strategy_lab.vibe_replay import STRATEGIES, load_fixture, replay_csv_files, replay_fixture


FIXTURE = "tests/fixtures/strategy_lab/aapl_getdata_12h_recorded_fixture_v1.json"


def test_replay_uses_real_fixture_with_governed_holdout() -> None:
    fixture, bars = load_fixture(FIXTURE)
    result = replay_fixture(fixture, bars)
    assert tuple(result["strategies"]) == STRATEGIES
    assert result["execution"] == "REPLAY_COMPLETED"
    assert result["oos"]["status"] == "OOS_VALIDATED"
    assert result["oos"]["holdout"]["status"] == "GOVERNED"
    assert result["oos"]["holdout"]["strategy_not_tuned_on_holdout"] is True
    assert result["provenance"]["fixture_digest"] == fixture["fixture_digest"]
    assert result["provenance"]["holdout_rows"] == 2


def test_cost_sensitivity_is_explicit_and_safety_stays_closed() -> None:
    fixture, bars = load_fixture(FIXTURE)
    result = replay_fixture(fixture, bars, ("b0",))
    scenarios = result["holdout"]["b0"]["cost_sensitivity"]
    assert [(item["commission_bps"], item["slippage_bps"]) for item in scenarios] == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (5.0, 5.0)]
    assert result["safety"] == {"radar_admission": "BLOCKED", "trade_execution": "NO", "paper_auto_ready": False, "paid_service_used": False}


def test_replay_report_is_json_serializable() -> None:
    fixture, bars = load_fixture(FIXTURE)
    json.dumps(replay_fixture(fixture, bars), sort_keys=True)


def test_csv_replay_preserves_source_hash_and_safety(tmp_path) -> None:
    path = tmp_path / "US.TEST_5m.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time_key", "open", "high", "low", "close", "symbol", "source"])
        writer.writeheader()
        for index in range(8):
            price = 100 + index
            writer.writerow({"time_key": f"2026-01-01 09:{35 + index:02d}:00", "open": price, "high": price + 1, "low": price - 1, "close": price + 0.5, "symbol": "US.TEST", "source": "LOCAL_FIXTURE"})
    result = replay_csv_files([path], ("b0", "v0.2"))
    assert result["symbols"] == ["US.TEST"]
    assert result["inputs"][0]["replay"]["provenance"]["fixture_digest"].startswith("sha256:")
    assert result["safety"]["trade_execution"] == "NO"
