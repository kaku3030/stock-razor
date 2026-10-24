import importlib.util
from pathlib import Path
import sys
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_s3_strict_no_add import strict_engine


def test_no_add_is_explicit_even_with_rounding_budget_and_cheaper_later_stop_distance():
    p=Path(__file__).resolve().parents[1]/'src/services/strategy_lab/s3_mtf.py'
    eng,_=strict_engine(p)
    spec=importlib.util.spec_from_file_location('old_engine',p)
    old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
    dates=['2024-03-06','2024-03-07','2024-03-08']
    s=pd.DataFrame({'open_at':[pd.Timestamp(x+' 09:30',tz='America/New_York') for x in dates],
                    'close_at':[pd.Timestamp(x+' 16:00',tz='America/New_York') for x in dates]})
    ends=[t for r in s.itertuples() for t in pd.date_range(r.open_at+pd.Timedelta(minutes=5),r.close_at,freq='5min')]
    b=pd.DataFrame(dict(end=ends,open=100.,close=100.,high=100.2,low=99.8,volume=100.))
    # A notional-capped first leg leaves risk unused. H1 confirms+1R then a
    # cheaper eligible opening releases enough symbol capacity for one share.
    b.loc[166:167,['open','close','high','low']]=[101.4,101.4,101.5,101.3]
    b.loc[168:,['open','close','high','low']]=[98.8,98.8,99.,98.75]
    ts=pd.Timestamp('2024-03-08 09:40:01',tz='America/New_York')
    sig=pd.DataFrame([dict(arm='A',decision_at=ts,signal_end=ts-pd.Timedelta(seconds=1),
         d1_end=ts-pd.Timedelta(days=1),structure_end=ts-pd.Timedelta(hours=4),setup_end=ts-pd.Timedelta(hours=4),
         signal_close=100.,stop=98.7,max_entry=1e9)])
    for mod in [old,eng]:mod.daily_allowed=lambda *_:True
    rr=old.Rules(first_risk_fraction=1.,symbol_cap=.1)
    _,before,_=old.replay({'X':b},s,{'X':sig},{'X':'T'},rules=rr,exit_on_daily_filter=False)
    _,after,_=eng.replay({'X':b},s,{'X':sig},{'X':'T'},rules=rr,exit_on_daily_filter=False)
    # The changed conditional forbids queueing under every capacity condition.
    assert not (after.reason=='ADD').any()
    assert (before.reason=='ADD').sum()==1
    assert (after.reason=='ENTRY').sum()==1
    # Exact target/entry clocks remain identical for the ordinary single leg.
    assert before[before.reason=='ENTRY'].price.tolist()==after[after.reason=='ENTRY'].price.tolist()
