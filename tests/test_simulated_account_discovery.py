from datetime import datetime, timezone

import pytest

from src.services.simulated_account_discovery import (
    AccountDiscoveryBlocked,
    AccountMode,
    discover_simulated_us_account,
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
