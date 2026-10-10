"""Offline deterministic OpenD watch churn simulation tests."""
from pathlib import Path

from src.services.ai_monitor.opend_watch_churn_simulator import (
    simulate_us_watch_churn,
)


def run(frames, **kwargs):
    return simulate_us_watch_churn(frames, **kwargs)


def test_repeated_watch_observations_required_before_hypothetical_add():
    result = run([["US.AMD"], ["US.AMD"], ["US.AMD"]])
    assert result["status"] == "SIMULATION_ONLY"
    assert result["simulated_add_count"] == 1
    assert result["simulated_remove_count"] == 0
    assert result["final_hypothetical_watch_count"] == 1
    assert result["subscription_changes"] == "NONE"
    assert result["provider_requests"] == 0
    assert result["provider_mutations"] == 0
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_one_frame_spike_is_filtered_by_hysteresis():
    result = run([["US.TSLA"], [], []])
    assert result["simulated_add_count"] == 0
    assert result["final_hypothetical_watch_count"] == 0
    assert result["hysteresis_block_events"] >= 1


def test_repeated_absence_is_required_before_hypothetical_removal():
    result = run([["US.AMD"], ["US.AMD"], [], [], []])
    assert result["simulated_add_count"] == 1
    assert result["simulated_remove_count"] == 1
    assert result["final_hypothetical_watch_count"] == 0


def test_hypothetical_slot_limit_does_not_trigger_preemption():
    result = run(
        [["US.AMD", "US.NVDA"], ["US.AMD", "US.NVDA"], ["US.TSLA"]],
        hypothetical_slots=1, max_changes_per_window=4)
    assert result["simulated_add_count"] == 1
    assert result["capacity_block_events"] >= 1
    assert result["max_hypothetical_watch_count"] == 1


def test_churn_rate_budget_is_bounded_per_window():
    result = run(
        [["US.AMD", "US.NVDA"], ["US.AMD", "US.NVDA"],
         ["US.AMD", "US.NVDA"], ["US.AMD", "US.NVDA"]],
        max_changes_per_window=1, window_frames=6)
    assert result["simulated_add_count"] == 1
    assert result["churn_budget_block_events"] >= 1


def test_churn_budget_releases_after_window():
    result = run(
        [["US.AMD", "US.NVDA"], ["US.AMD", "US.NVDA"],
         ["US.AMD", "US.NVDA"], ["US.AMD", "US.NVDA"]],
        max_changes_per_window=1, window_frames=2)
    assert result["simulated_add_count"] == 2


def test_invalid_or_duplicate_symbols_fail_closed():
    for frames in (
        [["AMD"]], [["US.amd"]], [["US.AMD", "US.AMD"]],
        [["US."]], [["US.AMD\nSECRET"]], ["not-a-list"], [[]] * 241,
    ):
        result = run(frames)
        assert result["status"] == "BLOCKED"
        assert result["subscription_changes"] == "NONE"


def test_bounds_and_boolean_parameters_fail_closed():
    for kw in (
        {"hypothetical_slots": 0}, {"min_consecutive_frames": 0},
        {"max_changes_per_window": True}, {"window_frames": 0},
        {"hypothetical_slots": 257}, {"max_changes_per_window": 257},
    ):
        assert run([["US.AMD"]], **kw)["status"] == "BLOCKED"


def test_output_does_not_expose_symbols_or_account_data():
    result = run([["US.PRIVATE123"], ["US.PRIVATE123"]])
    assert "US.PRIVATE123" not in str(result)
    assert result["subtype_entitlement"] == "NOT_VERIFIED"
    assert result["quota_qualification"] == "NOT_VERIFIED"


def test_no_network_or_opend_subscription_calls():
    source = (Path(__file__).resolve().parents[1] /
              "src/services/ai_monitor/opend_watch_churn_simulator.py").read_text(
                  encoding="utf-8")
    assert "import futu" not in source
    assert "import requests" not in source
    assert ".subscribe(" not in source
    assert ".unsubscribe(" not in source
    assert "place_order(" not in source
