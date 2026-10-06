from datetime import datetime, timedelta, timezone
from data_provider.market_bar_builder import aggregate_bars
from data_provider.market_data_adapter import Bar, SignalPermission, evaluate_health

START=datetime(2026,10,5,13,30,tzinfo=timezone.utc)
BLOCKED=evaluate_health(freshness=.5,completeness=1,timestamp=.5,provider=1,continuity=.5,cross_check=.5,quality_flags=("TIMESTAMP_MISMATCH","TIMESTAMP_SEMANTICS_UNVERIFIED"))
def b(i):
    t=START+timedelta(minutes=i)
    return Bar(symbol="US.AMD",market="us",asset_type="stock",timeframe="1m",bar_start=t,bar_end=t+timedelta(minutes=1),open=100+i,high=101+i,low=99+i,close=100.5+i,volume=10,amount=1000,provider="futu",feed="opend",source_timestamp=t,received_at=t+timedelta(seconds=5),session="regular",is_closed=True,is_complete=True,health=BLOCKED,quality_flags=BLOCKED.quality_flags)

def test_complete_five_minute_bar_preserves_blocked_evidence():
    out=aggregate_bars([b(i) for i in range(5)],"5m",as_of=START+timedelta(minutes=5))
    assert len(out)==1 and out[0].is_closed and out[0].is_complete
    assert out[0].volume==50 and out[0].close==104.5
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in out[0].quality_flags
    assert out[0].health.signal_permission is SignalPermission.BLOCKED

def test_missing_minute_makes_five_minute_bar_incomplete():
    out=aggregate_bars([b(i) for i in (0,1,3,4)],"5m",as_of=START+timedelta(minutes=5))
    assert len(out)==1 and not out[0].is_complete
    assert "MISSING_BAR" in out[0].quality_flags
    assert out[0].health.signal_permission is SignalPermission.BLOCKED
