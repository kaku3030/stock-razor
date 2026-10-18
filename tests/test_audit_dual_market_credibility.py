import json

import pandas as pd

from tools.research.audit_dual_market_credibility import audit_asset_set


def test_v11_audit_flags_calendar_episode_boundary(tmp_path):
    directory = tmp_path / "v11"
    directory.mkdir()
    pd.DataFrame([{"symbol": "US.QQQ", "status": "OK", "first_readable_date": "2019-05-08", "last_readable_date": "2026-10-16", "rows": 2}]).to_csv(directory / "x_coverage.csv", index=False)
    pd.DataFrame([
        {"strategy": "V10_BASELINE", "scope": "FULL_STRESS_2020", "cost_scenario": "5bp_fee_5bp_slippage", "start": "2020-01-01", "end": "2020-12-31", "cumulative_return": 0.1},
        {"strategy": "V10_BASELINE", "scope": "FULL_STRESS_2020", "cost_scenario": "10bp_fee_10bp_slippage", "start": "2020-01-01", "end": "2020-12-31", "cumulative_return": 0.09},
        {"strategy": "V10_BASELINE", "scope": "FULL_STRESS_2022", "cost_scenario": "5bp_fee_5bp_slippage", "start": "2022-01-01", "end": "2022-12-31", "cumulative_return": 0.1},
        {"strategy": "V10_BASELINE", "scope": "FULL_STRESS_2022", "cost_scenario": "10bp_fee_10bp_slippage", "start": "2022-01-01", "end": "2022-12-31", "cumulative_return": 0.09},
        {"strategy": "V10_BASELINE", "scope": "FULL_STRESS_2025", "cost_scenario": "5bp_fee_5bp_slippage", "start": "2025-01-01", "end": "2025-12-31", "cumulative_return": 0.1},
        {"strategy": "V10_BASELINE", "scope": "FULL_STRESS_2025", "cost_scenario": "10bp_fee_10bp_slippage", "start": "2025-01-01", "end": "2025-12-31", "cumulative_return": 0.09},
    ]).to_csv(directory / "x_metrics.csv", index=False)
    pd.DataFrame([
        {"date": "2020-01-01", "state": "NEUTRAL", "turnover": 1.0, "candidate": "V10_BASELINE", "cost_scenario": "5bp_fee_5bp_slippage"},
        {"date": "2020-01-02", "state": "RISK_ON", "turnover": 0.1, "candidate": "V10_BASELINE", "cost_scenario": "5bp_fee_5bp_slippage"},
    ]).to_csv(directory / "x_states.csv", index=False)
    pd.DataFrame([
        {"start": "2020-01-01", "end": "2020-01-01", "state": "NEUTRAL", "days": 1, "return": 0.0, "entry_turnover": 1.0, "candidate": "V10_BASELINE", "cost_scenario": "5bp_fee_5bp_slippage"},
        {"start": "2020-01-03", "end": "2020-01-03", "state": "RISK_ON", "days": 1, "return": 0.0, "entry_turnover": 0.1, "candidate": "V10_BASELINE", "cost_scenario": "5bp_fee_5bp_slippage"},
    ]).to_csv(directory / "x_episodes.csv", index=False)
    metadata = {"endpoint": "127.0.0.1:11111", "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ"}, "signal_timing": "closed_prior_rows_only_next_day_effective", "qfq_dividend_semantics": "UNKNOWN", "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN", "oos_status": "NOT_VERIFIED", "sha256": {}}
    (directory / "x_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (directory / "x_report.md").write_text("report", encoding="utf-8")

    _, summary = audit_asset_set(directory, "V1.1")
    checks = {row["check"]: row["status"] for row in summary["checks"]}
    assert checks["V1.1_episode_calendar_boundaries"] == "FAIL"
