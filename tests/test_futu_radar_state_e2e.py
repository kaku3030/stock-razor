from datetime import datetime, timedelta, timezone
import pandas as pd
from data_provider.market_data_adapter import MarketDataAdapter, SignalPermission, evaluate_health
from src.services.live_feed.futu_k1m_forming_accumulator import FormingMinuteBar
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar
from src.services.realtime_market_data import RealtimeMarketDataService
from src.services.stock_radar_v2.technical_state import StockRadarTechnicalStateService

START=datetime(2026,10,5,13,30,tzinfo=timezone.utc)
GOOD=evaluate_health(freshness=1,completeness=1,timestamp=1,provider=1,continuity=1,cross_check=1)
class Adapter(MarketDataAdapter):
    def get_latest_quote(self,s): raise NotImplementedError
    def get_bars(self,*a,**k): return []
    def subscribe(self,*a,**k): pass
    def get_session_status(self,m): return "regular"
    def get_provider_health(self): return GOOD
    def reconnect(self): return False

def test_opend_snapshot_reaches_radar_but_cannot_confirm_signal():
    service=RealtimeMarketDataService(Adapter(),max_minutes=120)
    for i in range(60):
        bar_start=START+timedelta(minutes=i)
        time_key=bar_start+timedelta(minutes=1)
        minute=FormingMinuteBar("US.AMD",time_key,100+i*.1,101+i*.1,99+i*.1,100.5+i*.1,100+i,10000+i,True)
        service.ingest(closed_futu_minute_to_bar(minute,received_at=time_key+timedelta(seconds=5)))
    snap=service.snapshot("US.AMD",as_of=START+timedelta(minutes=60))
    daily=pd.DataFrame({"date":pd.date_range("2026-07-01",periods=80,freq="D"),"open":[100+i*.2 for i in range(80)],"high":[101+i*.2 for i in range(80)],"low":[99+i*.2 for i in range(80)],"close":[100.5+i*.2 for i in range(80)],"volume":[1000+i for i in range(80)]})
    state=StockRadarTechnicalStateService().evaluate(snap,daily=daily)
    assert state.provider == "futu" and state.feed == "opend"
    assert state.signal_permission is SignalPermission.BLOCKED
    assert state.research_only is True and state.can_confirm_signal is False
    assert "timestamp_mismatch" not in state.technical.risk_flags
    assert "timestamp_semantics_unverified" in state.technical.risk_flags
    assert state.technical.intraday.confidence <= .65
    assert state.technical.hourly.confidence <= .65
