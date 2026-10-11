"""Cloud-native moomoo REST Paper schema is tested without OAuth/network."""

from datetime import datetime, timedelta, timezone

import pytest

from src.services.moomoo_rest_paper_discovery import (
    RestPaperDiscoveryBlocked,
    inspect_rest_us_sim_account_list,
)

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
ACCOUNT_ID = "80303779"


def response(*rows, ret_code=0):
    return {
        "ret_code": ret_code,
        "data": {
            "accounts": list(rows or [{
                "account_id": ACCOUNT_ID,
                "broker_id": 0,
                "market_id": 2,
                "intra_account_id": 0,
                "account_type": 0,
                "account_title": "example only",
            }]),
        },
    }


def inspect(payload=None, **kw):
    opts = {
        "expected_account_id": ACCOUNT_ID,
        "observed_at_utc": NOW,
        "now_utc": NOW,
        "read_scope_confirmed": True,
        "first_read_side_effect_approved": True,
    }
    opts.update(kw)
    return inspect_rest_us_sim_account_list(response() if payload is None else payload, **opts)


def test_valid_offline_schema_remains_non_activated_non_parity():
    got = inspect()
    assert got.account_id == ACCOUNT_ID
    assert got.market_id == 2
    assert got.schema_checked_only is True
    assert got.rest_user_authorization_independently_verified is False
    assert got.japan_account_entitlement_verified is False
    assert got.legacy_opend_account_parity_verified is False
    assert got.mobile_paper_account_parity_verified is False
    assert got.paper_auto_ready is False
    assert got.external_order_allowed is False
    assert got.live_trade is False


@pytest.mark.parametrize("option", [
    {"read_scope_confirmed": False},
    {"first_read_side_effect_approved": False},
    {"read_scope_confirmed": "YES"},
    {"first_read_side_effect_approved": "YES"},
])
def test_oauth_read_permission_and_first_call_side_effect_are_explicit(option):
    with pytest.raises(RestPaperDiscoveryBlocked, match="approval"):
        inspect(**option)


@pytest.mark.parametrize("payload", [
    {"ret_code": True, "data": {"accounts": []}},
    {"ret_code": 9, "data": {"accounts": []}},
    {"ret_code": 0, "data": {"accounts": {"not": "a list"}}},
    {"ret_code": 0, "data": {"accounts": [1]}},
    {"ret_code": 0, "data": {"accounts": []}},
    response({"account_id": ACCOUNT_ID, "market_id": 1, "broker_id": 0, "account_type": 0}),
    response({"account_id": ACCOUNT_ID, "market_id": True, "broker_id": 0, "account_type": 0}),
])
def test_failure_or_malformed_rest_response_never_qualifies(payload):
    with pytest.raises(RestPaperDiscoveryBlocked):
        inspect(payload)


def test_wrong_account_id_and_duplicate_expected_account_block():
    with pytest.raises(RestPaperDiscoveryBlocked, match="exactly one"):
        inspect(response({"account_id": "99999", "market_id": 2}))
    item = response()["data"]["accounts"][0]
    with pytest.raises(RestPaperDiscoveryBlocked, match="exactly one"):
        inspect(response(item, item))


def test_timestamp_ttl_and_missing_authentication_evidence_fails_closed():
    with pytest.raises(RestPaperDiscoveryBlocked, match="future or stale"):
        inspect(observed_at_utc=NOW - timedelta(seconds=61))
    with pytest.raises(RestPaperDiscoveryBlocked, match="future or stale"):
        inspect(observed_at_utc=NOW + timedelta(seconds=1))
    with pytest.raises(RestPaperDiscoveryBlocked, match="timezone"):
        inspect(now_utc=NOW.replace(tzinfo=None))


def test_private_ids_not_in_exception_messages():
    with pytest.raises(RestPaperDiscoveryBlocked) as caught:
        inspect(expected_account_id="PRIVATE_USER_IDENTIFIER")
    assert "PRIVATE_USER_IDENTIFIER" not in str(caught.value)
    assert ACCOUNT_ID not in str(caught.value)
