import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v05 import dynamic_tail_weights, metrics, STATIC_STRATEGIES


def test_static_candidates_are_fixed_and_fully_invested():
    assert set(STATIC_STRATEGIES) == {"QQQ_USMV_IEF_SHV", "QQQ_TAIL_IEF_SHV", "QQQ_DBMF_BTAL_SHV"}
    assert all(np.isclose(sum(weights.values()), 1.0) for weights in STATIC_STRATEGIES.values())


def test_dynamic_tail_changes_only_from_prior_observations():
    index = pd.date_range("2020-01-01", periods=250, freq="B")
    qqq = pd.Series(np.r_[np.linspace(100, 150, 220), np.linspace(150, 100, 30)], index=index)
    weights = dynamic_tail_weights(index, qqq)
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert weights.iloc[-1]["US.TAIL"] == 0.35


def test_metrics_include_pressure_and_turnover_fields():
    index = pd.date_range("2020-01-01", periods=3, freq="B")
    result = metrics(pd.Series([.01, -.03, .02], index=index), pd.Series([.02, -.04, -.01], index=index), pd.Series(.1, index=index), "x", 2020)
    assert result["qqq_down_3pct_up_rate"] == 0.0
    assert np.isclose(result["turnover"], 0.3)
