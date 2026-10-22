from decimal import Decimal

import pytest
from fastapi import HTTPException

from api.v1.endpoints.offline_simulation import run_offline_simulation
from api.v1.schemas.offline_simulation import OfflineSimulationRequest


def test_offline_simulation_returns_local_fill_without_external_io():
    result = run_offline_simulation(
        OfflineSimulationRequest(
            symbol="tsla",
            quantity=Decimal("1"),
            limit_price=Decimal("250"),
            simulate_fill=True,
        )
    )

    assert result.symbol == "TSLA"
    assert result.environment == "LOCAL_OFFLINE_SIMULATION"
    assert result.order_state == "FILLED"
    assert result.filled_quantity == "1"
    assert result.fill_source == "LOCAL_SCENARIO_FIXTURE"
    assert result.external_fill_confirmation is False
    assert result.broker_io is result.provider_io is result.live_trade is False


def test_offline_simulation_without_fill_stays_accepted():
    result = run_offline_simulation(
        OfflineSimulationRequest(symbol="TSLA", quantity="1", limit_price="250")
    )

    assert result.order_state == "ACCEPTED"
    assert result.filled_quantity == "0"
    assert result.fill_source == "NONE"


@pytest.mark.parametrize(
    "payload",
    [
        {"symbol": "600000.SH", "quantity": "101", "limit_price": "10"},
        {"symbol": "TSLA", "side": "SELL", "quantity": "1", "limit_price": "250"},
    ],
)
def test_offline_simulation_rejects_unsupported_scenarios(payload):
    with pytest.raises(HTTPException) as exc_info:
        run_offline_simulation(OfflineSimulationRequest(**payload))

    assert exc_info.value.status_code == 422


def test_offline_simulation_request_rejects_invalid_symbol():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OfflineSimulationRequest(symbol="not a ticker", quantity="1", limit_price="10")
