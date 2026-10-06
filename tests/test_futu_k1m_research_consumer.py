from datetime import datetime, timedelta, timezone

from data_provider.live_feed_types import ProviderEvent, ProviderEventKind, SemanticStreamKey
from data_provider.market_data_adapter import SignalPermission, evaluate_health
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import LiveFeedController
from src.services.live_feed.futu_k1m_closure_pipeline import FutuK1MClosurePipeline
from src.services.live_feed.futu_k1m_research_consumer import FutuK1MResearchConsumer
from src.services.realtime_market_data import RealtimeMarketDataService


NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)
KEY = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")
BLOCKED = evaluate_health(
    freshness=0.5,
    completeness=1,
    timestamp=0.5,
    provider=1,
    continuity=0.5,
    cross_check=0.5,
    quality_flags=("TIMESTAMP_SEMANTICS_UNVERIFIED",),
)


def row(time_key: str, close: float = 100.5, *, malformed: bool = False):
    payload = {
        "code": "US.AMD",
        "time_key": time_key,
        "open": 100.0,
        "high": max(101.0, close),
        "low": 99.0,
        "close": close,
        "volume": 10.0,
        "turnover": 1000.0,
    }
    if malformed:
        payload.pop("open")
    return payload


def event(payload) -> ProviderEvent:
    return ProviderEvent(
        runtime_instance_id="r1",
        provider_id="futu",
        controller_generation=0,
        observed_at_utc=NOW,
        observed_at_monotonic=1.0,
        event_kind=ProviderEventKind.DATA,
        semantic_stream_key=KEY,
        payload=payload,
        provider_timestamp_raw=str(payload.get("time_key")),
        provenance="PUSH",
    )


def controller_with_desired() -> LiveFeedController:
    controller = LiveFeedController(
        runtime_instance_id="r1",
        provider_id="futu",
        command_executor=FakeProviderCommandExecutor(),
        now_utc=lambda: NOW,
    )
    controller.request_add_desired(KEY)
    controller.process_pending()
    return controller


def cache() -> RealtimeMarketDataService:
    return RealtimeMarketDataService(
        None,
        session_status_provider=lambda _market: "regular",
        provider_health_provider=lambda: BLOCKED,
        max_minutes=60,
        now=lambda: NOW,
    )


def submit_rows(controller, *rows):
    for payload in rows:
        assert controller.submit_event(event(payload)).accepted
    controller.process_pending()


def test_writer_to_closure_to_ingest_only_cache_happy_path():
    controller = controller_with_desired()
    closure = FutuK1MClosurePipeline()
    market_data = cache()
    consumer = FutuK1MResearchConsumer(controller, closure, market_data)

    submit_rows(
        controller,
        row("2026-10-06 10:52:00", 100.8),
        row("2026-10-06 10:53:00", 101.2),
    )
    result = consumer.run_once()

    assert result.evidence_processed == 2
    assert result.closure_blocked == 0
    assert result.bars_ingested == 1
    assert result.stopped_reason is None
    bars = market_data.minute_bars("US.AMD")
    assert len(bars) == 1
    assert bars[0].bar_end == datetime(2026, 10, 6, 14, 52, tzinfo=timezone.utc)
    assert bars[0].health.signal_permission is SignalPermission.BLOCKED
    assert closure.peek_closed() is None


class FailOnceCache:
    def __init__(self, delegate):
        self.delegate = delegate
        self.fail = True

    def ingest(self, bar):
        if self.fail:
            self.fail = False
            raise RuntimeError("injected cache failure")
        return self.delegate.ingest(bar)


def test_cache_exception_keeps_closed_bar_unacked_for_next_run():
    controller = controller_with_desired()
    closure = FutuK1MClosurePipeline()
    delegate = cache()
    flaky = FailOnceCache(delegate)
    consumer = FutuK1MResearchConsumer(controller, closure, flaky)

    submit_rows(
        controller,
        row("2026-10-06 10:52:00", 100.8),
        row("2026-10-06 10:53:00", 101.2),
    )
    first = consumer.run_once()

    assert first.evidence_processed == 2
    assert first.bars_ingested == 0
    assert first.stopped_reason == "CACHE_INGEST_EXCEPTION:RuntimeError"
    pending = closure.peek_closed()
    assert pending is not None
    assert delegate.minute_bars("US.AMD") == ()

    second = consumer.run_once()
    assert second.evidence_processed == 0
    assert second.bars_ingested == 1
    assert second.stopped_reason is None
    assert closure.peek_closed() is None
    assert len(delegate.minute_bars("US.AMD")) == 1


def test_malformed_evidence_blocks_one_item_but_later_valid_items_continue():
    controller = controller_with_desired()
    closure = FutuK1MClosurePipeline()
    market_data = cache()
    consumer = FutuK1MResearchConsumer(controller, closure, market_data)

    submit_rows(
        controller,
        row("2026-10-06 10:51:00", malformed=True),
        row("2026-10-06 10:52:00", 100.8),
        row("2026-10-06 10:53:00", 101.2),
    )
    result = consumer.run_once()

    assert result.evidence_processed == 3
    assert result.closure_blocked == 1
    assert result.bars_ingested == 1
    assert result.stopped_reason is None
    assert len(market_data.minute_bars("US.AMD")) == 1


def test_max_events_does_not_pre_drain_remaining_controller_evidence():
    controller = controller_with_desired()
    closure = FutuK1MClosurePipeline()
    market_data = cache()
    consumer = FutuK1MResearchConsumer(controller, closure, market_data)

    submit_rows(
        controller,
        row("2026-10-06 10:52:00", 100.8),
        row("2026-10-06 10:53:00", 101.2),
    )

    first = consumer.run_once(max_events=1)
    assert first.evidence_processed == 1
    assert first.bars_ingested == 0

    second = consumer.run_once(max_events=1)
    assert second.evidence_processed == 1
    assert second.bars_ingested == 1


class RaisingClosure:
    def __init__(self):
        self.inner = FutuK1MClosurePipeline()

    def consume_event(self, _evidence):
        raise RuntimeError("injected closure failure")

    def peek_closed(self):
        return None

    def ack_closed(self, _bar):
        return False


def test_unexpected_closure_exception_stops_after_one_evidence_only():
    controller = controller_with_desired()
    market_data = cache()
    consumer = FutuK1MResearchConsumer(controller, RaisingClosure(), market_data)

    submit_rows(
        controller,
        row("2026-10-06 10:52:00"),
        row("2026-10-06 10:53:00"),
    )
    result = consumer.run_once(max_events=100)

    assert result.evidence_processed == 1
    assert result.stopped_reason == "CLOSURE_EXCEPTION:RuntimeError"
    remaining = controller.drain_applied_data_for_consumer()
    assert len(remaining) == 1


def test_closed_bar_ack_is_exact_and_non_destructive_on_mismatch():
    controller = controller_with_desired()
    closure = FutuK1MClosurePipeline()
    submit_rows(
        controller,
        row("2026-10-06 10:52:00", 100.8),
        row("2026-10-06 10:53:00", 101.2),
    )
    evidence = controller.drain_applied_data_for_consumer()
    closure.consume_event(evidence[0])
    closure.consume_event(evidence[1])
    bar = closure.peek_closed()
    assert bar is not None

    wrong = type(bar)(**{**bar.__dict__, "bar_start": bar.bar_start - timedelta(minutes=1)})
    try:
        closure.ack_closed(wrong)
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched ack must fail")

    assert closure.peek_closed() == bar
    assert closure.ack_closed(bar) is True
    assert closure.peek_closed() is None
