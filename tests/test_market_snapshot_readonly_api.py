"""Fail-closed tests for the snapshot endpoint without a provider or network."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.v1.endpoints.data import get_market_snapshot
from api.v1.schemas.market_snapshot import MarketSnapshotResponse


NOW = datetime(2026, 9, 17, 14, 31, tzinfo=timezone.utc)


class FakeSnapshotService:
    def __init__(self):
        self.calls = []

    def get_snapshot(self, symbol):
        self.calls.append(symbol)
        return {
            "symbol": symbol,
            "market": "us",
            "provider": "alpaca",
            "feed": "iex",
            "queried_at": NOW,
            "quote": {
                "price": 200.5,
                "source_timestamp": datetime(2026, 9, 17, 14, 30, tzinfo=timezone.utc),
                "received_at": NOW,
                "observed_latency_ms": 60000,
                "quality_flags": ["NOT_CROSS_CHECKED"],
            },
            "bars": [{
                "timeframe": "15m",
                "bar_start": datetime(2026, 9, 17, 14, 15, tzinfo=timezone.utc),
                "bar_end": datetime(2026, 9, 17, 14, 30, tzinfo=timezone.utc),
                "open": 200.0,
                "high": 201.0,
                "low": 199.0,
                "close": 200.5,
                "volume": 1000,
                "source_timestamp": datetime(2026, 9, 17, 14, 30, tzinfo=timezone.utc),
                "received_at": NOW,
                "is_closed": True,
                "is_complete": False,
                "quality_flags": ["MISSING_BAR"],
            }],
        }


def request(service=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(market_snapshot_service=service)))


def test_snapshot_endpoint_requires_independent_auth_even_with_admin_middleware_disabled(monkeypatch) -> None:
    service = FakeSnapshotService()
    monkeypatch.delenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", raising=False)
    with pytest.raises(HTTPException) as error:
        get_market_snapshot("NVDA", request(service), authorization="Bearer guessed")
    assert error.value.status_code == 401
    assert service.calls == []


def test_snapshot_endpoint_rejects_bad_bearer_before_provider_or_service(monkeypatch) -> None:
    service = FakeSnapshotService()
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", "example-test-token")
    with pytest.raises(HTTPException) as error:
        get_market_snapshot("NVDA", request(service), authorization="Bearer wrong")
    assert error.value.status_code == 401
    assert service.calls == []


def test_snapshot_endpoint_requires_an_existing_ai_monitor_runtime(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", "example-test-token")
    with pytest.raises(HTTPException) as error:
        get_market_snapshot("NVDA", request(), authorization="Bearer example-test-token")
    assert error.value.status_code == 503


def test_snapshot_endpoint_reads_once_and_preserves_incomplete_bar_flags(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", "example-test-token")
    service = FakeSnapshotService()
    result = get_market_snapshot("NVDA", request(service), authorization="Bearer example-test-token")
    assert service.calls == ["NVDA"]
    assert result.delivery_mode == "UNKNOWN"
    assert result.entitlement == "UNKNOWN"
    assert result.quote.source_timestamp == datetime(2026, 9, 17, 14, 30, tzinfo=timezone.utc)
    assert result.bars[0].is_closed is True
    assert result.bars[0].is_complete is False


def test_snapshot_read_evidence_is_unknown_and_does_not_authorize_runtime(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", "example-test-token")
    service = FakeSnapshotService()
    result = get_market_snapshot("NVDA", request(service), authorization="Bearer example-test-token")

    assert result.entitlement == "UNKNOWN"
    assert service.calls == ["NVDA"]
    assert "MISSING_BAR" in result.bars[0].quality_flags


def test_snapshot_response_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError):
        MarketSnapshotResponse.model_validate({
            "symbol": "NVDA", "market": "us", "provider": "alpaca",
            "feed": "iex", "queried_at": "2026-09-17T14:31:00",
        })
