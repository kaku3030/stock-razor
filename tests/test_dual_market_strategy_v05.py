import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v05 import dynamic_tail_weights, metrics, STATIC_STRATEGIES, OFFICIAL_INCEPTION, PHASE_STRATEGIES


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


def test_coverage_keeps_official_inception_separate_from_provider_readability():
    assert OFFICIAL_INCEPTION["US.QQQ"][0] == "1999-03-10"
    assert OFFICIAL_INCEPTION["US.SPY"][0] == "1993-01-22"
    assert OFFICIAL_INCEPTION["US.TLT"][0] == "2002-07-22"
    assert OFFICIAL_INCEPTION["US.IEF"][0] == "2002-07-22"


def test_phase_candidates_only_add_assets_after_observed_readable_dates():
    assert PHASE_STRATEGIES["2006_2011_QQQ_SPY_TLT_IEF"]["window"][0] == "2006-10-04"
    assert "US.BTAL" not in PHASE_STRATEGIES["2006_2011_QQQ_SPY_TLT_IEF"]["weights"]
    assert PHASE_STRATEGIES["2012_2016_QQQ_BTAL_TLT_IEF"]["window"][0] == "2012-01-06"
    assert PHASE_STRATEGIES["2017_2019_QQQ_TAIL_BTAL_IEF"]["window"][0] == "2017-04-06"
    assert PHASE_STRATEGIES["2019_2026_QQQ_DBMF_BTAL_IEF"]["window"][0] == "2019-05-08"
    assert all(np.isclose(sum(item["weights"].values()), 1.0) for item in PHASE_STRATEGIES.values())
