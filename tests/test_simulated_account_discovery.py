from datetime import datetime, timezone

import pytest

from src.services.simulated_account_discovery import (
    AccountDiscoveryBlocked,
    AccountMode,
    discover_simulated_us_account,
    discover_futu_us_stock_sim_account,
)


NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def row(**changes):
    value = {
        "acc_id": "sim-us-001",
        "trd_env": "SIMULATE",
        "market": "US",
        "authenticated": True,
    }
    value.update(changes)
    return value


def test_discovers_exactly_one_authenticated_us_simulated_account():
    result = discover_simulated_us_account(
        [row(), row(acc_id="real-us-001", trd_env="REAL")], observed_at=NOW
    )
    assert result.account_id == "sim-us-001"
    assert result.mode is AccountMode.SIMULATE
    assert result.market == "US"


@pytest.mark.parametrize(
    "rows,match",
    [
        ([row(trd_env="REAL")], "exactly one"),
        ([row(authenticated=False)], "exactly one"),
        ([row(market="HK")], "exactly one"),
        ([row(), row(acc_id="sim-us-002")], "exactly one"),
        ([row(trd_env="UNKNOWN")], "unsupported"),
        ([{"trd_env": "SIMULATE", "market": "US", "authenticated": True}], "acc_id"),
    ],
)
def test_discovery_fails_closed(rows, match):
    with pytest.raises(AccountDiscoveryBlocked, match=match):
        discover_simulated_us_account(rows, observed_at=NOW)


def test_observation_time_must_be_timezone_aware():
    with pytest.raises(AccountDiscoveryBlocked, match="timezone"):
        discover_simulated_us_account([row()], observed_at=NOW.replace(tzinfo=None))


def official_row(**changes):
    value = {
        "acc_id": 123456789,
        "trd_env": "SIMULATE",
        "trdmarket_auth": ["US"],
        "sim_acc_type": "STOCK_AND_OPTION",
        "acc_status": "ACTIVE",
    }
    value.update(changes)
    return value


def test_official_futu_account_identity_matches_numeric_sdk_id():
    matched = discover_futu_us_stock_sim_account(
        [official_row(), official_row(acc_id=91234, trd_env="REAL")],
        expected_account_id="123456789",
        observed_at=NOW,
        session_authenticated=True,
    )
    assert matched.account_id == "123456789"
    assert matched.market == "US"
    assert matched.mode == AccountMode.SIMULATE
    assert matched.authenticated is True


@pytest.mark.parametrize("change", [
    {"trd_env": "REAL"},
    {"trdmarket_auth": ["HK"]},
    {"trdmarket_auth": "US"},
    {"sim_acc_type": "FUTURES"},
    {"acc_status": "DISABLED"},
])
def test_official_futu_account_enforces_simulate_stock_active_us(change):
    with pytest.raises(AccountDiscoveryBlocked, match="not an active US stock SIMULATE"):
        discover_futu_us_stock_sim_account(
            [official_row(**change)],
            expected_account_id="123456789",
            observed_at=NOW,
            session_authenticated=True,
        )


def test_official_futu_account_requires_session_and_exact_identity():
    with pytest.raises(AccountDiscoveryBlocked, match="session"):
        discover_futu_us_stock_sim_account(
            [official_row()], expected_account_id="123456789", observed_at=NOW
        )
    with pytest.raises(AccountDiscoveryBlocked, match="exact simulated account"):
        discover_futu_us_stock_sim_account(
            [official_row()], expected_account_id="99999", observed_at=NOW,
            session_authenticated=True,
        )
    with pytest.raises(AccountDiscoveryBlocked, match="numeric account identity"):
        discover_futu_us_stock_sim_account(
            [official_row()], expected_account_id="not-an-id", observed_at=NOW,
            session_authenticated=True,
        )
    with pytest.raises(AccountDiscoveryBlocked, match="exact simulated account"):
        discover_futu_us_stock_sim_account(
            [official_row(), official_row()], expected_account_id="123456789",
            observed_at=NOW, session_authenticated=True,
        )


def test_official_futu_account_blocks_non_string_and_bool_ids():
    for value in (True, 123.456, None):
        with pytest.raises(AccountDiscoveryBlocked, match="exact simulated account"):
            discover_futu_us_stock_sim_account(
                [official_row(acc_id=value)], expected_account_id="123456789",
                observed_at=NOW, session_authenticated=True,
            )
