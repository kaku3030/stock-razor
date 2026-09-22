"""Isolated HTTP smoke for non-owning snapshot view; no provider/network/trades."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from data_provider.market_data_adapter import Bar, evaluate_health
from src.services.ai_monitor.market_snapshot_view import MarketSnapshotView
from src.services.realtime_market_data import MarketDataSnapshot, RealtimeMarketRuntimeOwner


NOW = datetime(2026, 9, 17, 13, 31, 15, tzinfo=timezone.utc)
START = NOW - timedelta(minutes=1, seconds=15)
HEALTH = evaluate_health(
    freshness=1, completeness=1, timestamp=1, provider=1,
    continuity=1, cross_check=1,
)
URL = "/api/v1/data/market-snapshot/NVDA"
TOKEN = "unit-test-only-snapshot-token"


class AlreadyOwnedCache:
    def __init__(self, *, empty=False, feed="iex"):
        self.reads = 0
        self.empty = empty
        self.feed = feed

    def seed(self, *args, **kwargs):
        raise AssertionError("read-only view attempted history seeding")

    def subscribe(self, *args, **kwargs):
        raise AssertionError("read-only view attempted a new provider subscription")

    def snapshot(self, symbol):
        self.reads += 1
        bars = () if self.empty else (Bar(
            symbol=symbol, market="us", asset_type="stock", timeframe="1m",
            bar_start=START, bar_end=START + timedelta(minutes=1),
            open=200, high=201, low=199, close=200.5, volume=100,
            provider="alpaca", feed=self.feed,
            source_timestamp=START + timedelta(minutes=1), received_at=NOW,
            session="regular", is_closed=True, is_complete=True,
            health=HEALTH,
        ),)
        return MarketDataSnapshot(
            symbol=symbol, as_of=NOW, minute_bars=bars, bars_15m=(), bars_1h=(),
            health=HEALTH, provider="alpaca" if bars else None,
            feed=self.feed if bars else None, fallback_from=None,
            fallback_reason=None,
        )


class FakeProvider:
    def __init__(self):
        self.subscribe_calls = 0
        self.closed = 0
        self.callback = None

    def get_latest_quote(self, symbol):
        raise AssertionError("owner lifecycle test must not request quotes")

    def get_bars(self, symbol, timeframe, start=None, end=None, limit=None):
        raise AssertionError("owner lifecycle test must not seed provider history")

    def subscribe(self, symbols, timeframe="1m", callback=None):
        self.subscribe_calls += 1
        self.callback = callback

    def emit(self, *, price, start=START):
        assert self.callback is not None
        self.callback(Bar(
            symbol="NVDA", market="us", asset_type="stock", timeframe="1m",
            bar_start=start, bar_end=start + timedelta(minutes=1),
            open=price, high=price, low=price, close=price, volume=100,
            provider="alpaca", feed="iex", source_timestamp=start + timedelta(minutes=1),
            received_at=NOW, session="regular", is_closed=True, is_complete=True,
            health=HEALTH,
        ))

    def get_session_status(self, market):
        return "closed"

    def get_provider_health(self):
        return HEALTH

    def reconnect(self):
        return True

    def close(self):
        self.closed += 1


class CloseFailingProvider(FakeProvider):
    def close(self):
        self.closed += 1
        raise RuntimeError("provider close failed")


def test_runtime_owner_starts_one_service_and_ignores_duplicate_start():
    providers = []

    def make_provider():
        provider = FakeProvider()
        providers.append(provider)
        return provider

    owner = RealtimeMarketRuntimeOwner(make_provider, ["NVDA", "NVDA"])
    first = owner.start()
    second = owner.start()

    assert first is second
    assert owner.service is first
    assert len(providers) == 1
    assert providers[0].subscribe_calls == 1

    owner.stop()
    owner.stop()
    assert owner.service is None
    assert providers[0].closed == 1


def test_runtime_owner_closes_before_restart_and_keeps_one_active_service():
    providers = []

    def make_provider():
        provider = FakeProvider()
        providers.append(provider)
        return provider

    owner = RealtimeMarketRuntimeOwner(make_provider, ["NVDA"])
    first = owner.start()
    second = owner.restart()

    assert second is not first
    assert owner.service is second
    assert len(providers) == 2
    assert providers[0].closed == 1
    assert providers[1].closed == 0
    assert providers[1].subscribe_calls == 1

    owner.stop()
    assert providers[1].closed == 1


def test_runtime_owner_fails_closed_without_provider():
    owner = RealtimeMarketRuntimeOwner(lambda: None, ["NVDA"])

    with pytest.raises(RuntimeError, match="provider is unavailable"):
        owner.start()

    assert owner.service is None


def test_runtime_owner_closes_provider_when_startup_subscription_fails():
    provider = FakeProvider()

    def fail_subscribe(symbols, timeframe="1m", callback=None):
        provider.subscribe_calls += 1
        raise RuntimeError("subscription startup failed")

    provider.subscribe = fail_subscribe
    owner = RealtimeMarketRuntimeOwner(lambda: provider, ["NVDA"])

    with pytest.raises(RuntimeError, match="subscription startup failed"):
        owner.start()

    assert owner.service is None
    assert provider.closed == 1


def test_runtime_owner_retains_failed_provider_and_blocks_restart():
    providers = []

    def make_provider():
        provider = CloseFailingProvider()
        providers.append(provider)
        return provider

    owner = RealtimeMarketRuntimeOwner(make_provider, ["NVDA"])
    first = owner.start()

    with pytest.raises(RuntimeError, match="provider close failed"):
        owner.stop()

    assert owner.service is first
    assert len(providers) == 1
    with pytest.raises(RuntimeError, match="provider close failed"):
        owner.restart()
    assert owner.service is first
    assert len(providers) == 1


def test_default_factory_never_constructs_a_snapshot_owner_and_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_AUTH_ENABLED", "false")
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", TOKEN)
    app = create_app(static_dir=tmp_path / "unbuilt")
    assert getattr(app.state, "market_snapshot_service", None) is None
    response = TestClient(app).get(URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503


def test_injected_existing_owner_is_read_once_and_does_not_subscribe(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_AUTH_ENABLED", "false")
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", TOKEN)
    owner = AlreadyOwnedCache()
    app = create_app(
        static_dir=tmp_path / "unbuilt",
        market_snapshot_service=MarketSnapshotView(owner),
    )
    client = TestClient(app)
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={"Authorization": "Bearer incorrect"}).status_code == 401
    assert owner.reads == 0
    response = client.get(URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    result = response.json()
    assert owner.reads == 1
    assert result["entitlement"] == "UNKNOWN"
    assert result["delivery_mode"] == "UNKNOWN"
    assert result["feed"] == "iex"
    assert result["quote"]["price"] == 200.5
    assert "BAR_DERIVED_PRICE" in result["quote"]["quality_flags"]
    assert result["bars"][0]["source_timestamp"] == result["quote"]["source_timestamp"]


def test_missing_data_from_existing_owner_stays_503(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_AUTH_ENABLED", "false")
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", TOKEN)
    owner = AlreadyOwnedCache(empty=True)
    app = create_app(
        static_dir=tmp_path / "unbuilt",
        market_snapshot_service=MarketSnapshotView(owner),
    )
    response = TestClient(app).get(URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503
    assert owner.reads == 1


def test_unverified_feed_is_not_silently_fabricated():
    owner = AlreadyOwnedCache(feed=None)
    assert MarketSnapshotView(owner).get_snapshot("NVDA") is None
    assert owner.reads == 1


def test_factory_rejects_non_snapshot_service(tmp_path):
    with pytest.raises(ValueError, match="read-only market snapshot view"):
        create_app(static_dir=tmp_path / "unbuilt", market_snapshot_service=object())


def test_callback_to_authenticated_api_survives_restart_without_old_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_AUTH_ENABLED", "false")
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", TOKEN)
    providers = []

    def make_provider():
        provider = FakeProvider()
        providers.append(provider)
        return provider

    owner = RealtimeMarketRuntimeOwner(
        make_provider, ["NVDA"], service_kwargs={"now": lambda: NOW}
    )
    view = MarketSnapshotView(owner)
    app = create_app(static_dir=tmp_path / "unbuilt", market_snapshot_service=view)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=headers).status_code == 503
    assert providers == []
    first = owner.start()
    assert owner.start() is first
    assert len(providers) == 1
    assert providers[0].subscribe_calls == 1
    assert client.get(URL, headers=headers).status_code == 503
    providers[0].emit(price=200.5)
    assert first.minute_bars("NVDA")[0].close == 200.5
    initial = client.get(URL, headers=headers)
    assert initial.status_code == 200
    assert initial.json()["quote"]["price"] == 200.5
    assert datetime.fromisoformat(initial.json()["quote"]["source_timestamp"]) == START + timedelta(minutes=1)

    owner.stop()
    assert providers[0].closed == 1
    assert client.get(URL, headers=headers).status_code == 503
    second = owner.start()
    assert second is not first
    assert len(providers) == 2
    assert providers[1].subscribe_calls == 1
    assert client.get(URL, headers=headers).status_code == 503
    providers[1].emit(price=211.0, start=START + timedelta(minutes=1))
    updated = client.get(URL, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["quote"]["price"] == 211.0
    assert datetime.fromisoformat(updated.json()["quote"]["source_timestamp"]) == START + timedelta(minutes=2)
    assert first.minute_bars("NVDA")[0].close == 200.5
    assert client.get(URL).status_code == 401
    assert len(providers) == 2
    owner.stop()
    assert providers[1].closed == 1
    assert client.get(URL, headers=headers).status_code == 503


def test_main_server_composes_one_owner_and_releases_on_shutdown(monkeypatch):
    import sys
    import threading
    import types
    import asyncio
    import main
    import uvicorn

    monkeypatch.setenv("STOCK_RAZOR_ALPACA_STREAM_SYMBOLS", "NVDA,NVDA")
    monkeypatch.setenv("APCA_API_KEY_ID", "unit-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "unit-secret")
    monkeypatch.setenv("STOCK_RAZOR_ALPACA_STREAM_FEED", "iex")
    monkeypatch.setenv("ADMIN_AUTH_ENABLED", "false")
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", TOKEN)
    streams = []

    class OfflineStream:
        def __init__(self, *args, **kwargs):
            self.stop_event = threading.Event()
            self.started = threading.Event()
            self.subscriptions = []
            self.closed = 0
            streams.append(self)

        def subscribe_bars(self, handler, *symbols):
            self.subscriptions.append((handler, symbols))

        def subscribe_updated_bars(self, handler, *symbols):
            self.subscriptions.append((handler, symbols))

        def run(self):
            self.started.set()
            self.stop_event.wait(5)

        def stop(self):
            self.closed += 1
            self.stop_event.set()

    class OfflineServer:
        def __init__(self, config):
            self.app = config.app
            self.started = False
            self.done = threading.Event()
            servers.append(self)

        def run(self):
            self.started = True
            self.done.wait(5)

    servers = []
    class OfflineConfig:
        def __init__(self, app, **kwargs):
            self.app = app

    monkeypatch.setitem(sys.modules, "alpaca", types.ModuleType("alpaca"))
    monkeypatch.setitem(sys.modules, "alpaca.data", types.ModuleType("alpaca.data"))
    enums = types.ModuleType("alpaca.data.enums")
    enums.DataFeed = lambda feed: feed
    monkeypatch.setitem(sys.modules, "alpaca.data.enums", enums)
    monkeypatch.setitem(sys.modules, "alpaca.data.live", types.ModuleType("alpaca.data.live"))
    stock = types.ModuleType("alpaca.data.live.stock")
    stock.StockDataStream = OfflineStream
    monkeypatch.setitem(sys.modules, "alpaca.data.live.stock", stock)
    monkeypatch.setattr(uvicorn, "Config", OfflineConfig)
    monkeypatch.setattr(uvicorn, "Server", OfflineServer)
    main.start_api_server("127.0.0.1", 0, types.SimpleNamespace(log_level="INFO"))
    assert len(streams) == 1
    assert streams[0].started.wait(1)
    assert len(streams[0].subscriptions) == 2
    assert streams[0].subscriptions[0][1] == ("NVDA",)
    client = TestClient(servers[0].app)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=headers).status_code == 503
    asyncio.run(streams[0].subscriptions[0][0]({"T": "b", "S": "NVDA", **{
        "t": START.isoformat(), "o": 200, "h": 201, "l": 199,
        "c": 200.5, "v": 100,
    }}))
    assert client.get(URL, headers=headers).status_code == 200
    servers[0].done.set()
    for _ in range(100):
        if streams[0].closed:
            break
        threading.Event().wait(0.01)
    assert streams[0].closed == 1
    assert client.get(URL, headers=headers).status_code == 503
