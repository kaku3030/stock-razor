from datetime import datetime, timedelta, timezone

from src.services.live_feed.futu_k1m_warm_start_runtime import (
    seed_futu_k1m_research_cache,
)


NOW = datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)


def _session(day: str, symbol: str):
    start = datetime.strptime(day + " 09:31:00", "%Y-%m-%d %H:%M:%S")
    rows = []
    for index in range(390):
        stamp = start + timedelta(minutes=index)
        price = 100 + index / 100
        rows.append(
            {
                "code": symbol,
                "time_key": stamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price + 0.1,
                "volume": 1000 + index,
                "turnover": 100000 + index,
            }
        )
    return rows


class _Cache:
    def __init__(self):
        self.bars = {}

    def ingest(self, bar):
        key = (bar.symbol, bar.bar_start)
        old = self.bars.get(key)
        self.bars[key] = bar
        return old != bar


def test_runtime_warm_start_pages_then_seeds_one_complete_session():
    symbol = "US.AMD"
    rows = [*_session("2026-10-05", symbol), *_session("2026-10-06", symbol)]
    calls = []

    def fetch_page(code, start, end, page_key):
        calls.append((code, start, end, page_key))
        if page_key is None:
            return rows[:500], b"page-2"
        assert page_key == b"page-2"
        return rows[500:], None

    cache = _Cache()
    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=fetch_page,
        market_data=cache,
        received_at=NOW,
    )

    assert result.status == "PASS"
    assert result.seeded_total == 390
    assert len(cache.bars) == 390
    item = result.symbols[0]
    assert item.status == "PASS"
    assert item.session_date == "2026-10-05"
    assert item.query_pages == 2
    assert item.planned_bar_count == 390
    assert item.closure_anchor_time_key == "2026-10-06 09:31:00"
    assert calls[0][3] is None
    assert calls[1][3] == b"page-2"


def test_page_limit_blocks_without_partial_seed():
    symbol = "US.AMD"

    def fetch_page(code, start, end, page_key):
        return _session("2026-10-05", symbol)[:100], b"more"

    cache = _Cache()
    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=fetch_page,
        market_data=cache,
        received_at=NOW,
        max_pages=2,
    )

    assert result.status == "BLOCKED"
    assert result.seeded_total == 0
    assert cache.bars == {}
    assert result.symbols[0].reasons == ("HISTORY_PAGE_LIMIT_EXCEEDED",)


def test_one_symbol_failure_is_partial_and_does_not_kill_other_seed():
    amd = [*_session("2026-10-05", "US.AMD"), *_session("2026-10-06", "US.AMD")]

    def fetch_page(code, start, end, page_key):
        if code == "US.NVDA":
            raise RuntimeError("quota")
        return amd, None

    cache = _Cache()
    result = seed_futu_k1m_research_cache(
        ["US.AMD", "US.NVDA"],
        fetch_page=fetch_page,
        market_data=cache,
        received_at=NOW,
    )

    assert result.status == "PARTIAL"
    assert result.seeded_total == 390
    assert result.symbols[0].status == "PASS"
    assert result.symbols[1].status == "BLOCKED"
    assert result.symbols[1].reasons == ("HISTORY_QUERY_EXCEPTION:RuntimeError",)


def test_no_provider_anchor_never_partially_seeds_latest_session():
    symbol = "US.AMD"
    latest = _session("2026-10-06", symbol)

    cache = _Cache()
    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=lambda *args: (latest, None),
        market_data=cache,
        received_at=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.seeded_total == 0
    assert cache.bars == {}


def test_runtime_warm_start_result_remains_research_only():
    symbol = "US.AMD"
    rows = [*_session("2026-10-05", symbol), *_session("2026-10-06", symbol)]

    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=lambda *args: (rows, None),
        market_data=_Cache(),
        received_at=NOW,
    )
    payload = result.to_dict()

    assert payload["status"] == "PASS"
    assert payload["historical_query"] is True
    assert payload["realtime_currentness_proven"] is False
    assert payload["bar_closure_promotion_authorized"] is False
    assert payload["radar_admission"] == "BLOCKED"
    assert payload["live_trade"] is False

