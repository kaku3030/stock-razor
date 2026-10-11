"""Prevent write-capable moomoo MCP OAuth grants entering read-only Radar."""

import pytest

from src.services.moomoo_cloud_oauth_scope import (
    MoomooOAuthPilotMode,
    assess_moomoo_readonly_oauth_grant,
)


def gate(scopes, *, account="123456789", mode=MoomooOAuthPilotMode.ACCOUNT_READBACK):
    return assess_moomoo_readonly_oauth_grant(
        scopes, pilot_mode=mode, expected_account_id=account
    )


def test_exact_account_read_scopes_are_only_structure_not_authority():
    result = gate("quote:read trade:read accid:123456789")
    assert result.scoped_input_status == "SCOPED_INPUTS_CONSISTENT"
    assert not result.reasons
    assert result.quote_read_requested is True
    assert result.trade_read_requested is True
    assert result.oauth_session_independently_verified is False
    assert result.account_entitlement_verified is False
    assert result.first_get_side_effect_approved is False
    assert result.paper_auto_ready is False
    assert result.provider_io_allowed is False
    assert result.broker_mutation_allowed is False
    assert result.live_trade is False


def test_quote_only_does_not_receive_real_or_paper_account_tools():
    assert gate("quote:read", mode=MoomooOAuthPilotMode.QUOTE_ONLY, account=None).scoped_input_status == "SCOPED_INPUTS_CONSISTENT"
    assert "QUOTE_ONLY_HAS_ACCOUNT_ACCESS" in gate(
        "quote:read trade:read", mode=MoomooOAuthPilotMode.QUOTE_ONLY
    ).reasons


@pytest.mark.parametrize("scopes", [
    "quote:read trade:read trade:write accid:123456789",
    "quote:read trade:read quote:write accid:123456789",
    "quote:read trade:read accid:*",
    "quote:read trade:read accid:123456789 accid:9876",
    "quote:read trade:read accid:123456789 unknown:manage",
    "trade:read accid:123456789",
    "quote:read trade:read accid:123456789 accid:123456789",
    "quote:read quote:read trade:read accid:123456789",
])
def test_unauthorized_scope_shapes_are_blocked(scopes):
    r = gate(scopes)
    assert r.scoped_input_status == "BLOCKED"
    assert r.broker_mutation_allowed is False
    assert r.live_trade is False


@pytest.mark.parametrize("bad", ["", None, 123, " " * 10, "quote:read " * 400])
def test_invalid_grants_are_blocked(bad):
    assert gate(bad).scoped_input_status == "BLOCKED"


def test_grant_without_exact_expected_account_blocks_without_id_in_reasons():
    r = gate("quote:read trade:read accid:987654321")
    assert "EXACT_ACCOUNT_SCOPE_NOT_PROVEN" in r.reasons
    assert "987654321" not in str(r)
    assert "123456789" not in str(r)


def test_raw_scope_is_not_in_dataclass_or_serialized_report():
    r = gate("quote:read trade:read accid:123456789")
    assert "accid:" not in str(r)
    assert "trade:write" not in str(r)
