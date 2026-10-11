"""Ensure external Paper readback preflight never grants broker permission."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.services.external_simulator_readonly_preflight import (
    PaperReadOnlyScopeStatus,
    PaperReadOnlySlice,
    assess_external_sim_readonly_preflight,
)
from src.services.simulated_account_discovery import (
    AccountMode,
    SimulatedAccountDiscovery,
)

NOW = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)
ACCOUNT = SimulatedAccountDiscovery(
    account_id="123456789",
    mode=AccountMode.SIMULATE,
    market="US",
    authenticated=True,
    observed_at=NOW,
)


def observations():
    return [
        PaperReadOnlySlice(
            family=family,
            account_id=ACCOUNT.account_id,
            mode="SIMULATE",
            market="US",
            session_generation="session-1011",
            observed_at_utc=NOW,
            query_ok=True,
            row_count=1 if family == "BALANCE" else 0,
        )
        for family in ("BALANCE", "POSITIONS", "OPEN_ORDERS", "FILLS")
    ]


def assess(*, account=ACCOUNT, rows=None, session="session-1011", now=NOW):
    return assess_external_sim_readonly_preflight(
        account, observations() if rows is None else rows,
        expected_session_generation=session, now_utc=now,
    )


def test_consistent_evidence_does_not_promote_broker_permission():
    result = assess()
    assert result.status is PaperReadOnlyScopeStatus.SCOPED_INPUTS_CONSISTENT
    assert result.reasons == ()
    assert result.observations_checked == 4
    assert result.research_only
    assert result.broker_identity_independently_verified is False
    assert result.paper_auto_ready is False
    assert result.broker_mutation_allowed is False
    assert result.live_trade is False


@pytest.mark.parametrize("field,value,reason", [
    ("account_id", "987654321", "READBACK_ACCOUNT_SCOPE_MISMATCH"),
    ("mode", "REAL", "READBACK_ACCOUNT_SCOPE_MISMATCH"),
    ("market", "HK", "READBACK_ACCOUNT_SCOPE_MISMATCH"),
    ("session_generation", "another-run", "READBACK_SESSION_MISMATCH"),
    ("query_ok", False, "READBACK_QUERY_FAILED"),
    ("row_count", -1, "READBACK_ROW_COUNT_INVALID"),
    ("row_count", True, "READBACK_ROW_COUNT_INVALID"),
    ("observed_at_utc", NOW - timedelta(seconds=61), "READBACK_FUTURE_OR_STALE"),
    ("observed_at_utc", NOW + timedelta(microseconds=1), "READBACK_FUTURE_OR_STALE"),
])
def test_malformed_or_cross_session_readback_is_blocked(field, value, reason):
    rows = observations()
    rows[1] = replace(rows[1], **{field: value})
    result = assess(rows=rows)
    assert result.status is PaperReadOnlyScopeStatus.BLOCKED
    assert reason in result.reasons
    assert result.broker_mutation_allowed is False


def test_missing_duplicate_readbacks_never_pass():
    rows = observations()
    assert "INCOMPLETE_READBACKS" in assess(rows=rows[:-1]).reasons
    rows[-1] = replace(rows[-1], family="BALANCE")
    result = assess(rows=rows)
    assert "DUPLICATE_READBACK_FAMILY" in result.reasons
    assert "MISSING_READBACK_FAMILY" in result.reasons


def test_nonflat_account_or_existing_open_orders_require_manual_review():
    for family, reason in (
        ("POSITIONS", "EXISTING_POSITIONS_REQUIRE_OPERATOR_REVIEW"),
        ("OPEN_ORDERS", "EXISTING_OPEN_ORDERS_REQUIRE_OPERATOR_REVIEW"),
    ):
        rows = observations()
        idx = next(i for i, item in enumerate(rows) if item.family == family)
        rows[idx] = replace(rows[idx], row_count=1)
        assert reason in assess(rows=rows).reasons


def test_account_discovery_must_be_fresh_and_us_simulate():
    assert "DISCOVERY_FUTURE_OR_STALE" in assess(
        account=replace(ACCOUNT, observed_at=NOW - timedelta(seconds=61))
    ).reasons
    assert "SIM_ACCOUNT_DISCOVERY_UNVERIFIED" in assess(
        account=replace(ACCOUNT, mode=AccountMode.REAL)
    ).reasons
    assert "SIM_ACCOUNT_DISCOVERY_UNVERIFIED" in assess(
        account=replace(ACCOUNT, authenticated=False)
    ).reasons


def test_timezones_boundary_and_invalid_session_proof():
    rows = observations()
    rows[1] = replace(rows[1], observed_at_utc=NOW - timedelta(seconds=60))
    result = assess(rows=rows)
    assert result.status is PaperReadOnlyScopeStatus.SCOPED_INPUTS_CONSISTENT
    assert "SESSION_GENERATION_UNVERIFIED" in assess(session="").reasons
    assert "NOW_NOT_TIMEZONE_AWARE" in assess(now=NOW.replace(tzinfo=None)).reasons
    assert "READBACK_TIMESTAMP_INVALID" in assess(
        rows=[replace(rows[0], observed_at_utc=NOW.replace(tzinfo=None)), *rows[1:]]
    ).reasons


def test_no_private_account_identity_is_in_failure_reasons():
    rows = observations()
    rows[0] = replace(rows[0], account_id="SENSITIVE_ACCOUNT_ID")
    status = assess(rows=rows)
    assert "SENSITIVE_ACCOUNT_ID" not in str(status)
    assert "123456789" not in str(status)
    assert status.broker_mutation_allowed is False
