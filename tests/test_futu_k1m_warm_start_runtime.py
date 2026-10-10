from datetime import datetime, timedelta, timezone

from data_provider.market_data_adapter import evaluate_health
from src.services.live_feed.futu_k1m_warm_start_runtime import (
    seed_futu_k1m_research_cache,
)
from src.services.realtime_market_data import RealtimeMarketDataService


NOW = datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)
MARKET_NOW = datetime(2026, 10, 7, 13, 57, 48, tzinfo=timezone.utc)


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


def _three_sessions_with_anchor(symbol: str):
    return [
        *_session("2026-10-02", symbol),
        *_session("2026-10-05", symbol),
        *_session("2026-10-06", symbol),
        dict(_session("2026-10-07", symbol)[0]),
    ]


def _three_sessions_without_anchor(symbol: str):
    return [
        *_session("2026-10-02", symbol),
        *_session("2026-10-05", symbol),
        *_session("2026-10-06", symbol),
    ]


class _Cache:
    def __init__(self):
        self.bars = {}

    def ingest(self, bar):
        key = (bar.symbol, bar.bar_start)
        old = self.bars.get(key)
        self.bars[key] = bar
        return old != bar


def test_runtime_warm_start_pages_then_seeds_three_complete_sessions():
    symbol = "US.AMD"
    rows = _three_sessions_with_anchor(symbol)
    calls = []

    def fetch_page(code, start, end, page_key):
        calls.append((code, start, end, page_key))
        if page_key is None:
            return rows[:500], b"page-2"
        if page_key == b"page-2":
            return rows[500:1000], b"page-3"
        assert page_key == b"page-3"
        return rows[1000:], None

    cache = _Cache()
    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=fetch_page,
        market_data=cache,
        received_at=NOW,
    )

    assert result.status == "PASS"
    assert result.required_sessions == 3
    assert result.seeded_total == 1170
    assert len(cache.bars) == 1170
    item = result.symbols[0]
    assert item.status == "PASS"
    assert item.session_date == "2026-10-06"
    assert item.session_dates == ("2026-10-02", "2026-10-05", "2026-10-06")
    assert item.query_pages == 3
    assert item.planned_bar_count == 1170
    assert item.closure_anchor_time_key == "2026-10-07 09:31:00"
    assert item.closure_anchor_time_keys == (
        "2026-10-05 09:31:00",
        "2026-10-06 09:31:00",
        "2026-10-07 09:31:00",
    )
    assert item.closure_methods == (
        "NEXT_TIME_KEY_PROGRESS",
        "NEXT_TIME_KEY_PROGRESS",
        "NEXT_TIME_KEY_PROGRESS",
    )
    assert calls[0][3] is None
    assert calls[1][3] == b"page-2"
    assert calls[2][3] == b"page-3"


def test_runtime_warm_start_seeds_prior_day_terminal_session_without_anchor():
    symbol = "US.AMD"
    rows = _three_sessions_without_anchor(symbol)
    cache = _Cache()

    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=lambda *args: (rows, None),
        market_data=cache,
        received_at=NOW,
    )

    assert result.status == "PASS"
    assert result.seeded_total == 1170
    assert len(cache.bars) == 1170
    item = result.symbols[0]
    assert item.status == "PASS"
    assert item.session_date == "2026-10-06"
    assert item.session_dates == ("2026-10-02", "2026-10-05", "2026-10-06")
    assert item.closure_anchor_time_key is None
    assert item.closure_anchor_time_keys == (
        "2026-10-05 09:31:00",
        "2026-10-06 09:31:00",
    )
    assert item.closure_methods == (
        "NEXT_TIME_KEY_PROGRESS",
        "NEXT_TIME_KEY_PROGRESS",
        "QUALIFIED_PRIOR_SESSION_FULL_GRID",
    )


def test_runtime_catches_up_current_session_closed_bars_without_tail():
    symbol = "US.AMD"
    rows = [
        *_session("2026-10-02", symbol),
        *_session("2026-10-05", symbol),
        *_session("2026-10-06", symbol),
        *_session("2026-10-07", symbol)[:28],
    ]
    cache = _Cache()

    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=lambda *args: (rows, None),
        market_data=cache,
        received_at=MARKET_NOW,
    )

    assert result.status == "PASS"
    assert result.seeded_total == 1170
    assert result.current_session_catchup_seeded_total == 27
    assert result.current_session_catchup_unchanged_total == 0
    assert len(cache.bars) == 1197
    item = result.symbols[0]
    assert item.current_session_catchup_status == "PASS"
    assert item.current_session_catchup_date == "2026-10-07"
    assert item.current_session_catchup_planned_bar_count == 27
    assert item.current_session_catchup_seeded_count == 27
    assert item.current_session_catchup_unchanged_count == 0
    assert item.current_session_catchup_unresolved_tail_time_key == "2026-10-07 09:58:00"
    assert item.current_session_catchup_closure_method == "NEXT_TIME_KEY_PROGRESS"
    assert item.current_session_catchup_reason is None
    latest = max(cache.bars.values(), key=lambda bar: bar.bar_end)
    assert latest.bar_end == datetime(2026, 10, 7, 13, 57, tzinfo=timezone.utc)
    assert latest.quality_flags == ("HISTORICAL_QUERY",)


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
    amd = _three_sessions_with_anchor("US.AMD")

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
    assert result.seeded_total == 1170
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


def test_two_proven_sessions_do_not_partially_seed_three_session_contract():
    symbol = "US.AMD"
    rows = [
        *_session("2026-10-05", symbol),
        *_session("2026-10-06", symbol),
        dict(_session("2026-10-07", symbol)[0]),
    ]

    cache = _Cache()
    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=lambda *args: (rows, None),
        market_data=cache,
        received_at=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.seeded_total == 0
    assert cache.bars == {}
    assert result.symbols[0].reasons[0] == (
        "INSUFFICIENT_CLOSURE_PROVEN_SESSIONS:2/3"
    )


def test_runtime_warm_start_result_remains_research_only():
    symbol = "US.AMD"
    rows = _three_sessions_with_anchor(symbol)

    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=lambda *args: (rows, None),
        market_data=_Cache(),
        received_at=NOW,
    )
    payload = result.to_dict()

    assert payload["status"] == "PASS"
    assert payload["required_sessions"] == 3
    assert payload["seeded_total"] == 1170
    assert payload["historical_query"] is True
    assert payload["realtime_currentness_proven"] is False
    assert payload["bar_closure_promotion_authorized"] is False
    assert payload["radar_admission"] == "BLOCKED"
    assert payload["live_trade"] is False


def test_three_session_seed_produces_hourly_ready_canonical_aggregates():
    symbol = "US.AMD"
    rows = _three_sessions_with_anchor(symbol)
    provider_health = evaluate_health(
        freshness=1,
        completeness=1,
        timestamp=1,
        provider=1,
        continuity=1,
        cross_check=1,
    )
    service = RealtimeMarketDataService(
        None,
        session_status_provider=lambda _market: "closed",
        provider_health_provider=lambda: provider_health,
        max_minutes=1600,
        now=lambda: NOW,
    )

    result = seed_futu_k1m_research_cache(
        [symbol],
        fetch_page=lambda *args: (rows, None),
        market_data=service,
        received_at=NOW,
    )
    snapshot = service.snapshot(symbol, as_of=NOW)

    assert result.status == "PASS"
    assert len(snapshot.minute_bars) == 1170
    assert len(snapshot.bars_5m) == 234
    assert len(snapshot.bars_15m) == 78
    assert len(snapshot.bars_1h) == 21
