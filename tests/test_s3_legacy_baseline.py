"""Recovered-rule tests; artificial prices are NOT historical performance."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.services.strategy_lab.s3_legacy_baseline import (
    LEGACY_SIGNAL_MODEL, build_legacy_candidates, build_legacy_signals, legacy_profile,
)
from src.services.strategy_lab.s3_mtf import prepare_replay


def test_exact_profile_full_range_and_center_edges():
    window=pd.DataFrame(dict(low=[1.],high=[22.],volume=[210.]))
    assert legacy_profile(window)==(1.5,1.,16.)


def test_profile_neighbor_volume_tie_expands_left_first():
    window=pd.DataFrame(dict(low=[1.,10.,11.,12.],high=[22.,10.,11.,12.],volume=[0.,30.,100.,30.]))
    assert legacy_profile(window)==(11.5,10.,12.)


def test_profile_flat_range_is_unknown():
    result=legacy_profile(pd.DataFrame(dict(low=[10.],high=[10.],volume=[100.])))
    assert np.isnan(result).all()


def fixture():
    # Reuse the fixed source-independent synthetic generator, then create ten
    # consecutive rising/volume-growing hourly bars at the end of the history.
    spec=importlib.util.spec_from_file_location('s3_synthetic_helper',Path(__file__).with_name('test_s3_mtf.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    bars,schedule=helper.synthetic_history()
    cache=prepare_replay({'X':bars},schedule)
    tail=cache.frames['X',60].tail(10)
    for j,row in enumerate(tail.itertuples()):
        mask=(bars.end>row.start)&(bars.end<=row.end)
        price=200.+j
        bars.loc[mask,'open']=price-.1
        bars.loc[mask,'close']=price
        bars.loc[mask,'high']=price+.1
        bars.loc[mask,'low']=price-.2
        bars.loc[mask,'volume']=10000.*1.5**j
    return bars,schedule


def test_srvp_failure_still_consumes_five_hour_base_cooldown(monkeypatch):
    b,s=fixture()
    calls=[]
    def profile(window):
        calls.append(window.copy())
        return (np.nan,)*3 if len(calls)==1 else (100.,100.,10000.)
    monkeypatch.setattr('src.services.strategy_lab.s3_legacy_baseline.legacy_profile',profile)
    candidates=build_legacy_candidates(b,s)
    assert len(candidates)==2
    assert candidates.h1_index.diff().iloc[1]==5
    assert candidates.srvp_pass.tolist()==[False,True]
    assert (candidates.legacy_signal_model==LEGACY_SIGNAL_MODEL).all()
    assert (candidates.arm=='A').all()
    assert (candidates.max_entry==np.finfo(float).max).all()
    # Profile excludes the candidate itself and contains exactly prior100 H1.
    assert all(len(x)==100 for x in calls)
    assert all(x.end.iloc[-1]<row.signal_end for x,row in zip(calls,candidates.itertuples()))


def test_signal_adapter_filters_only_after_cooldown(monkeypatch):
    b,s=fixture()
    calls=[]
    def profile(window):
        calls.append(1)
        return (np.nan,)*3 if len(calls)==1 else (100.,100.,10000.)
    monkeypatch.setattr('src.services.strategy_lab.s3_legacy_baseline.legacy_profile',profile)
    result=build_legacy_signals(b,s)
    assert len(result)==1 and result.srvp_pass.iloc[0]
    assert len(calls)==2


def test_prior_low_mean_range_and_including_signal_volume_are_exact(monkeypatch):
    b,s=fixture()
    monkeypatch.setattr('src.services.strategy_lab.s3_legacy_baseline.legacy_profile',lambda _:(100.,100.,10000.))
    cache=prepare_replay({'X':b},s)
    candidates=build_legacy_candidates(b,s,prepared=cache,symbol='X')
    assert len(candidates)>0
    h=cache.frames['X',60]
    for row in candidates.itertuples():
        i=row.h1_index
        expected=min(float(h.low.iloc[i-20:i].min()),
                     float(h.close.iloc[i])-1.5*float((h.high-h.low).iloc[i-19:i+1].mean()))
        assert row.stop==pytest.approx(expected)
        assert h.volume.iloc[i]>1.2*h.volume.iloc[i-19:i+1].mean()
        assert row.d1_available_at<=row.decision_at
        assert row.decision_at==row.signal_end+pd.Timedelta(seconds=1)
    uncached=build_legacy_candidates(b,s)
    pd.testing.assert_frame_equal(candidates,uncached,check_exact=True)


def test_future_daily_close_cannot_change_earlier_legacy_signals(monkeypatch):
    b,s=fixture()
    monkeypatch.setattr('src.services.strategy_lab.s3_legacy_baseline.legacy_profile',lambda _:(100.,100.,10000.))
    before=build_legacy_signals(b,s)
    assert len(before)>0
    cutoff=before.decision_at.iloc[0]
    assert cutoff<s.close_at.iloc[-1]
    assert (before.d1_available_at<=before.decision_at).all()
    # Change the remainder of the decision day and every later day. Their
    # completed daily close is not yet known to this first hourly decision.
    b.loc[b.end>cutoff,['open','high','low','close']]*=100
    after=build_legacy_signals(b,s)
    pd.testing.assert_frame_equal(before[before.decision_at<=cutoff].reset_index(drop=True),
                                  after[after.decision_at<=cutoff].reset_index(drop=True),check_exact=True)


def test_cache_source_mutation_is_rejected():
    b,s=fixture()
    cache=prepare_replay({'X':b},s)
    b.loc[0,'volume']+=1
    with pytest.raises(ValueError,match='PREPARED_INPUT_CHANGED'):
        build_legacy_signals(b,s,prepared=cache,symbol='X')
