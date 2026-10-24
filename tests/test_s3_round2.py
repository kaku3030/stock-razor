from pathlib import Path
import sys
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_s3_round2 as m


def test_campaign_add_attribution_and_boundary_assignment():
    # Same symbol can re-enter exactly at the previous exit timestamp.
    t=pd.DataFrame([dict(symbol='X',entry_at='2024-01-02T15:00Z',exit_at='2024-01-03T15:00Z',
                        units=15,exit_price=12.,cash_spent=160.16,net_pnl=19.66)])
    e=pd.DataFrame([dict(symbol='X',time='2024-01-02T15:00Z',reason='ENTRY',units=10,price=10.),
                    dict(symbol='X',time='2024-01-02T16:00Z',reason='ADD',units=5,price=12.),
                    dict(symbol='X',time='2024-01-03T15:00Z',reason='ENTRY',units=100,price=12.)])
    x=m.split_legs(t,e).iloc[0]
    assert x.first_leg_net==pytest.approx(19.78)
    assert x.add_leg_net==pytest.approx(-.12)
    assert x.fees==pytest.approx(.34)
    e.loc[0,'units']=11
    with pytest.raises(ValueError,match='LEG_UNITS'):m.split_legs(t,e)


def test_daily_baseline_does_not_trade_on_forming_close():
    d=pd.DataFrame(dict(start=pd.date_range('2020-01-01',periods=205,tz='UTC'),
                        end=pd.date_range('2020-01-01 06:30',periods=205,tz='UTC'),
                        open=[10.]*205,close=[10.]*200+[11.]*5))
    left=d.start.iloc[200];right=d.end.iloc[-1]
    a=m.simple_baseline({'X':d},left,right,10,True)
    changed=d.copy();changed.loc[202:,'close']=20
    b=m.simple_baseline({'X':changed},left,right,10,True)
    assert a.equity.iloc[0]==100000 # day200 spike not known at open
    assert a.iloc[:2].equals(b.iloc[:2])
    # Shares can appreciate above the initial60% allocation; cash is unborrowed.
    assert (a.equity*(1-a.gross_exposure)).min()>=40000


def test_buy_hold_costs_and_cash_are_reconciled():
    d=pd.DataFrame(dict(start=pd.date_range('2020-01-01',periods=2,tz='UTC'),
                        end=pd.date_range('2020-01-01 06:30',periods=2,tz='UTC'),
                        open=[10.,10.],close=[10.,10.]))
    x=m.simple_baseline({'X':d},d.start.iloc[0],d.end.iloc[-1],10,False)
    assert x.equity.iloc[-1]==pytest.approx(100000-5994*10*.002)
    assert x.gross_exposure.iloc[-1]==0
