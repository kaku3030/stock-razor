import csv
import json

from src.services.strategy_lab.vibe_replay import STRATEGIES, load_fixture, replay_csv_files, replay_fixture


FIXTURE = "tests/fixtures/strategy_lab/aapl_getdata_12h_recorded_fixture_v1.json"


def test_replay_uses_real_fixture_with_diagnostic_holdout() -> None:
    fixture, bars = load_fixture(FIXTURE)
    result = replay_fixture(fixture, bars)
    assert tuple(result["strategies"]) == STRATEGIES
    assert result["execution"] == "REPLAY_COMPLETED"
    assert result["input_kind"] == "FIXTURE_SMOKE"
    assert result["data_audit"]["historical_replay_eligibility"] == "BLOCKED"
    assert result["strategy_rule_contract"]["status"] == "EXPLORATORY_PROXY_NOT_CANONICAL"
    assert result["strategy_rule_contract"]["canonical_strategy_spec"] == "NOT_VERIFIED"
    assert result["oos"]["status"] == "HOLDOUT_REPLAYED_RESEARCH_ONLY"
    assert result["oos"]["holdout"]["status"] == "DIAGNOSTIC_ONLY"
    assert result["oos"]["holdout"]["strategy_not_tuned_on_holdout"] == "NOT_VERIFIED"
    assert result["provenance"]["fixture_digest"] == fixture["fixture_digest"]
    assert result["provenance"]["holdout_rows"] == 2
    assert result["holdout"]["b0"]["gross"]["max_drawdown"] >= 0
    assert result["holdout"]["b0"]["gross"]["max_drawdown_status"] == "COMPUTED_FROM_BAR_LOW_CLOSE_MARK_TO_MARKET"
    assert len(result["holdout"]["b0"]["gross"]["equity_curve"]) == 2
    assert result["holdout"]["benchmark"]["name"] == "BUY_AND_HOLD"
    assert result["holdout"]["benchmark"]["gross"]["total_return"] == result["holdout"]["b0"]["gross"]["total_return"]
    assert len(result["holdout"]["benchmark"]["cost_sensitivity"]) == 4
    assert result["walk_forward"]["status"] == "BLOCKED_INSUFFICIENT_SAMPLE"
    assert result["walk_forward"]["leakage_check"] == "PASS"
    assert result["walk_forward"]["train"]["dataset_hash"].startswith("sha256:")
    assert result["walk_forward"]["holdout"]["dataset_hash"].startswith("sha256:")


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
    assert result["inputs"][0]["data_audit"]["historical_replay"]["eligibility"] == "BLOCKED"
    assert result["data_audit"]["status"] == "BLOCKED"
    assert result["safety"]["trade_execution"] == "NO"


def test_metrics_include_net_equity_and_drawdown_for_cost_scenarios() -> None:
    fixture, bars = load_fixture(FIXTURE)
    result = replay_fixture(fixture, bars, ("b0",))
    gross = result["train"]["b0"]["gross"]
    net = result["train"]["b0"]["cost_sensitivity"][2]
    assert gross["trade_count"] == 1
    assert gross["ending_equity"] == 1.0 + gross["total_return"]
    assert len(gross["equity_curve"]) == len(result["provenance"]["train_rows"] * [None])
    assert net["commission_bps"] == 2.0
    assert net["slippage_bps"] == 2.0
    assert net["total_return"] < gross["total_return"]
