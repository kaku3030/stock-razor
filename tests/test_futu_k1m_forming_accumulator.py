from src.services.live_feed.futu_k1m_forming_accumulator import FutuK1MFormingAccumulator


def row(t, close, volume=10):
    return {"code":"US.AMD","time_key":t,"open":100,"high":max(101,close),"low":99,"close":close,"volume":volume,"turnover":1000}


def test_same_minute_updates_replace_forming_bar_without_closing():
    a=FutuK1MFormingAccumulator()
    closed,forming=a.ingest(row("2026-10-05 10:52:00",100.5,10))
    assert closed is None and not forming.is_closed
    closed,forming=a.ingest(row("2026-10-05 10:52:00",100.8,20))
    assert closed is None and forming.close == 100.8 and forming.volume == 20 and not forming.is_closed


def test_next_minute_is_only_closure_evidence():
    a=FutuK1MFormingAccumulator()
    a.ingest(row("2026-10-05 10:52:00",100.8,20))
    closed,forming=a.ingest(row("2026-10-05 10:53:00",101.2,5))
    assert closed is not None and closed.is_closed and closed.start.minute == 52 and closed.close == 100.8
    assert forming.start.minute == 53 and not forming.is_closed


def test_out_of_order_minute_fails_closed():
    a=FutuK1MFormingAccumulator()
    a.ingest(row("2026-10-05 10:53:00",101))
    try:
        a.ingest(row("2026-10-05 10:52:00",100))
    except ValueError as exc:
        assert "out-of-order" in str(exc)
    else:
        raise AssertionError("out-of-order minute must fail closed")

def test_gap_closes_prior_but_does_not_invent_missing_minutes():
    a=FutuK1MFormingAccumulator()
    a.ingest(row("2026-10-05 10:52:00",100.8))
    closed,forming=a.ingest(row("2026-10-05 10:55:00",102.0))
    assert closed is not None and closed.start.minute == 52
    assert forming.start.minute == 55


def test_symbols_are_isolated():
    a=FutuK1MFormingAccumulator()
    a.ingest(row("2026-10-05 10:52:00",100.8))
    nvda=row("2026-10-05 10:52:00",190.0)
    nvda["code"]="US.NVDA"
    closed,forming=a.ingest(nvda)
    assert closed is None and forming.symbol == "US.NVDA"
    assert a.current("US.AMD").close == 100.8
