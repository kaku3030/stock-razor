import pandas as pd
import pytest

from tools.research.dual_market_strategy_v18_credibility import audit


def _frame() -> pd.DataFrame:
    rows = []
    for strategy in ("A_STATIC", "B_DYNAMIC", "AB_BLEND"):
        for date, net in zip(pd.date_range("2021-01-04", periods=3, freq="B"), (0.01, -0.01, 0.02)):
            rows.append({
                "date": date, "strategy": strategy, "cost_scenario": "5bp_fee_5bp_slippage",
                "start_nav": 1.0, "nav": 1.0 * (1 + net), "net_return": net,
                "gross_return": net, "transaction_cost": 0.0, "turnover": 0.0,
                "price_US.QQQ": 100.0, "target_weight_sum": 1.0,
            })
    return pd.DataFrame(rows)


def test_credibility_audit_marks_historical_forward_as_not_true_oos(tmp_path):
    input_csv = tmp_path / "input.csv"
    _frame().to_csv(input_csv, index=False)
    result = audit(input_csv, tmp_path / "out")
    payload = (tmp_path / "out" / "stock_razor_dual_market_strategy_v18_credibility_checks.json").read_text()
    assert "NOT_VERIFIED" in payload
    assert result["forward"].endswith("fixed_forward.csv")


def test_credibility_audit_rejects_misaligned_dates(tmp_path):
    frame = _frame()
    frame.loc[(frame.strategy == "AB_BLEND") & (frame.date == pd.Timestamp("2021-01-04")), "date"] = pd.Timestamp("2021-01-07")
    input_csv = tmp_path / "input.csv"
    frame.to_csv(input_csv, index=False)
    with pytest.raises(ValueError, match="exact trading-date set"):
        audit(input_csv, tmp_path / "out")
