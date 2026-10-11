"""Legacy US SIM snapshots remain separate from strategy P&L and new fills."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.legacy_sim_inventory import (
    LegacySimPosition, assess_legacy_sim_inventory,
)

NOW = datetime(2026, 10, 11, 13, tzinfo=timezone.utc)
HOLDINGS = (
    LegacySimPosition("US.AAA", "LONG", Decimal("10")),
    LegacySimPosition("US.BBB", "LONG", Decimal("20")),
    LegacySimPosition("US.CCC", "LONG", Decimal("30")),
    LegacySimPosition("US.DDD", "LONG", Decimal("40")),
)


def assess(**overrides):
    kwargs = dict(
        observed_account_id="123456",
        expected_account_id="123456",
        account_mode="SIMULATE",
        account_market="US",
        session_authenticated=True,
        broker_observed_at_utc=NOW,
        now_utc=NOW,
        user_ui_positions=HOLDINGS,
    )
    positions = overrides.pop("positions", HOLDINGS)
    kwargs.update(overrides)
    return assess_legacy_sim_inventory(positions, **kwargs)


def test_four_historical_ui_matches_never_qualify_new_paper_or_strategy_pnl():
    result = assess()
    assert result.status == "QUARANTINED"
    assert result.position_count == 4
    assert result.user_ui_comparison == "MATCH_NOT_PROOF_OF_FILLS"
    assert not result.old_pnl_strategy_eligible
    assert not result.independent_realized_fills_proven
    assert not result.paper_auto_ready
    assert not result.broker_mutation_allowed
    assert not result.live_trade


def test_ui_difference_is_blocked_and_not_silently_normalized():
    ui = (replace(HOLDINGS[0], quantity=Decimal("11")), *HOLDINGS[1:])
    result = assess(user_ui_positions=ui)
    assert result.status == "BLOCKED"
    assert "USER_UI_BROKER_POSITION_MISMATCH" in result.reasons


def test_real_account_and_wrong_account_id_are_blocked():
    assert "NON_US_SIM_ACCOUNT" in assess(account_mode="REAL").reasons
    assert "SIM_ACCOUNT_IDENTITY_NOT_PROVEN" in assess(
        observed_account_id="123457"
    ).reasons


def test_stale_broker_data_cannot_qualify_snapshot():
    result = assess(broker_observed_at_utc=NOW - timedelta(minutes=5))
    assert result.status == "QUARANTINED"
    assert "BROKER_READBACK_FUTURE_OR_STALE" in result.reasons
    assert not result.paper_auto_ready


def test_reject_duplicate_or_invalid_and_negative_positions():
    for positions in (
        HOLDINGS + (HOLDINGS[0],),
        (replace(HOLDINGS[0], quantity=Decimal("-1")),),
        (replace(HOLDINGS[0], symbol="US.AAA\\nBAD"),),
    ):
        assert assess(positions=positions).status == "BLOCKED"


def test_absent_ui_is_not_equated_with_proof():
    result = assess(user_ui_positions=None)
    assert result.status == "QUARANTINED"
    assert result.user_ui_comparison == "NOT_SUPPLIED"
