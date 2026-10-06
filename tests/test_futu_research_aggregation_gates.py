from datetime import datetime, timedelta, timezone
from data_provider.market_data_adapter import MarketDataAdapter, SignalPermission, evaluate_health
from src.services.live_feed.futu_k1m_forming_accumulator import FormingMinuteBar
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar
from src.services.realtime_market_data import RealtimeMarketDataService

START=datetime(2026,10,5,13,30,tzinfo=timezone.utc)
GOOD=evaluate_health(freshness=1,completeness=1,timestamp=1,provider=1,continuity=1,cross_check=1)
class Adapter(MarketDataAdapter):
    def get_latest_quote(self,symbol): raise NotImplementedError
    def get_bars(self,*a,**k): return []
    def subscribe(self,*a,**k): pass
    def get_session_status(self,market): return "regular"
    def get_provider_health(self): return GOOD
    def reconnect(self): return False

def b(i):
    t=START+timedelta(minutes=i)
    end_label=t+timedelta(minutes=1)
    m=FormingMinuteBar("US.AMD",end_label,100+i,101+i,99+i,100.5+i,10,1000,True)
    return closed_futu_minute_to_bar(m,received_at=end_label+timedelta(seconds=5))

def test_complete_15m_does_not_launder_unverified_timestamp():
    s=RealtimeMarketDataService(Adapter(),max_minutes=60)
    for i in range(15): s.ingest(b(i))
    snap=s.snapshot("US.AMD",as_of=START+timedelta(minutes=15))
    assert len(snap.bars_5m)==3 and all(bar.is_complete and bar.is_closed for bar in snap.bars_5m)
    assert all("TIMESTAMP_SEMANTICS_UNVERIFIED" in bar.quality_flags for bar in snap.bars_5m)
    assert all(bar.health.signal_permission is SignalPermission.BLOCKED for bar in snap.bars_5m)
    assert len(snap.bars_15m)==1 and snap.bars_15m[0].is_complete and snap.bars_15m[0].is_closed
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in snap.bars_15m[0].quality_flags
    assert snap.bars_15m[0].health.signal_permission is SignalPermission.BLOCKED

def test_missing_source_minute_stays_incomplete_and_blocked():
    s=RealtimeMarketDataService(Adapter(),max_minutes=60)
    for i in range(15):
        if i != 7: s.ingest(b(i))
    bar=s.snapshot("US.AMD",as_of=START+timedelta(minutes=15)).bars_15m[0]
    assert not bar.is_complete and "MISSING_BAR" in bar.quality_flags
    assert bar.health.signal_permission is SignalPermission.BLOCKED
