from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.external_simulator_contract import (
    ExternalSimOrderRequest,
    ExternalSimulatorBlocked,
    SimulatedAccountEvidence,
    SimulatorMode,
    SoftwareStopStatus,
    admit_external_sim_order,
)


NOW = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)


def evidence(**changes):
    values = dict(
        account_id="sim-123",
        observed_account_id="sim-123",
        mode=SimulatorMode.SIMULATE,
        observed_mode=SimulatorMode.SIMULATE,
        market="US",
        authenticated=True,
        observed_at=NOW - timedelta(seconds=2),
    )
    values.update(changes)
    return SimulatedAccountEvidence(**values)


def request(**changes):
    values = dict(
        symbol="AAPL",
        side="BUY",
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        valid_until=NOW + timedelta(minutes=5),
        protective_stop_status=SoftwareStopStatus.SIM_ONLY_UNPROTECTED_IF_DISCONNECTED,
    )
    values.update(changes)
    return ExternalSimOrderRequest(**values)


def admit(**changes):
    evidence_changes = changes.pop("evidence", {})
    request_changes = changes.pop("request", {})
    return admit_external_sim_order(
        evidence(**evidence_changes),
        request(**request_changes),
        now=NOW,
        allowed_symbols=frozenset({"AAPL"}),
        max_order_notional=Decimal("250"),
        max_order_quantity=Decimal("2"),
        max_price=Decimal("200"),
        **changes,
    )


def test_admits_bounded_simulate_only_order_without_submission():
    result = admit()
    assert result.venue == "MOOMOO_SIMULATE_ONLY"
    assert result.account_id == "sim-123"
    assert result.protective_stop_status is SoftwareStopStatus.SIM_ONLY_UNPROTECTED_IF_DISCONNECTED
    assert result.max_orders == 1


@pytest.mark.parametrize(
    "evidence_changes,request_changes,match",
    [
        ({"mode": SimulatorMode.REAL}, {}, "SIMULATE"),
        ({"observed_mode": SimulatorMode.REAL}, {}, "SIMULATE"),
        ({"observed_account_id": "sim-other"}, {}, "identity"),
        ({}, {"symbol": "MSFT"}, "allowlisted"),
        ({}, {"valid_until": NOW - timedelta(seconds=1)}, "expired"),
        ({}, {"limit_price": Decimal("201")}, "price"),
        ({}, {"quantity": Decimal("3")}, "quantity"),
        ({}, {"protective_stop_status": "BROKER_ACK"}, "software-only"),
    ],
)
def test_external_sim_contract_fails_closed(evidence_changes, request_changes, match):
    with pytest.raises(ExternalSimulatorBlocked, match=match):
        admit(evidence=evidence_changes, request=request_changes)


def test_ttl_and_order_count_are_bounded():
    with pytest.raises(ExternalSimulatorBlocked, match="TTL"):
        admit(request={"valid_until": NOW + timedelta(minutes=16)})
    with pytest.raises(ExternalSimulatorBlocked, match="exactly one"):
        admit(max_orders=2)


def test_simulated_account_observation_must_be_fresh():
    with pytest.raises(ExternalSimulatorBlocked, match="stale"):
        admit(evidence={"observed_at": NOW - timedelta(seconds=61)})
    # Exact documented boundary remains valid; no runtime request occurs.
    boundary = admit(evidence={"observed_at": NOW - timedelta(seconds=60)})
    assert boundary.venue == "MOOMOO_SIMULATE_ONLY"


def test_simulated_account_observation_cannot_be_from_future():
    with pytest.raises(ExternalSimulatorBlocked, match="future"):
        admit(evidence={"observed_at": NOW + timedelta(microseconds=1)})


def test_account_freshness_does_not_override_simulation_mode():
    with pytest.raises(ExternalSimulatorBlocked, match="SIMULATE"):
        admit(evidence={"observed_at": NOW, "mode": SimulatorMode.REAL})
