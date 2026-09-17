"""Isolated HTTP smoke for non-owning snapshot view; no provider/network/trades."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from data_provider.market_data_adapter import Bar, evaluate_health
from src.services.ai_monitor.market_snapshot_view import MarketSnapshotView
from src.services.realtime_market_data import MarketDataSnapshot


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
