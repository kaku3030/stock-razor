"""Synthetic only. Existing manual holdings never count as new strategy fills."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.legacy_sim_inventory import LegacySimPosition
from src.services.sim_legacy_shadow_attribution import (
    ShadowStrategyFill,
    review_legacy_sim_strategy_deltas,
)

NOW = datetime(2026, 10, 12, 13, tzinfo=timezone.utc)
START = NOW - timedelta(minutes=2)
BEFORE = START - timedelta(seconds=1)
OBS = NOW - timedelta(seconds=1)
BASELINE = (
    LegacySimPosition("US.AMD", "LONG", Decimal("1100")),
    LegacySimPosition("US.NVDA", "LONG", Decimal("500")),
    LegacySimPosition("US.SOFA", "LONG", Decimal("300")),
    LegacySimPosition("US.TSLA", "LONG", Decimal("140")),
)
FILL = ShadowStrategyFill(
    "provider-test-fill-1", "strategy-test-action-1", "999000123",
    "US.AMD", "BUY", Decimal("2"), START + timedelta(seconds=15),
)


def review(*, broker=None, fills=(), baseline=BASELINE, **changes):
    args = dict(
        account_id="999000123",
        legacy_baseline=baseline,
        current_broker_positions=BASELINE if broker is None else broker,
        reported_strategy_fills=fills,
        baseline_observed_at_utc=BEFORE,
        strategy_started_at_utc=START,
        current_observed_at_utc=OBS,
        now_utc=NOW,
        operator_accepted_legacy=True,
    )
    args.update(changes)
    return review_legacy_sim_strategy_deltas(**args)


def updated_amd(qty):
    return (replace(BASELINE[0], quantity=Decimal(qty)), *BASELINE[1:])


def test_original_old_positions_are_isolated_without_strategy_pnl():
    result = review()
    assert result.status == "LEGACY_BASELINE_ONLY"
    assert result.legacy_instrument_count == 4
    assert result.strategy_instrument_count == 0
    assert result.reviewed_fill_count == 0
    assert result.provenance_status == "NOT_INDEPENDENTLY_ATTESTED"
    assert not result.strategy_pnl_eligible
    assert not result.paper_auto_ready
    assert not result.broker_mutation_allowed
    assert result.radar_admission == "BLOCKED"
    assert result.source_arbiter_admission == "BLOCKED"
    assert not result.live_trade


def test_new_strategy_buy_of_same_legacy_symbol_only_attributes_delta():
    result = review(fills=(FILL,), broker=updated_amd("1102"))
    assert result.status == "SHADOW_REVIEW_ONLY"
    assert result.strategy_instrument_count == 1
    assert result.reviewed_fill_count == 1
    assert result.legacy_instrument_count == 4
    assert not result.independent_realized_fills_proven
    assert not result.strategy_pnl_eligible


def test_selling_old_manually_owned_amd_is_not_new_strategy_short_fill():
    selling_old = replace(FILL, side="SELL", quantity=Decimal("1"))
    result = review(
        fills=(selling_old,), broker=updated_amd("1099")
    )
    assert result.status == "BLOCKED"
    assert result.reason == "LEGACY_POSITION_SALE_NOT_STRATEGY_FILL"


def test_strategy_buy_then_sell_only_strategy_owned_units():
    sell = replace(
        FILL, fill_id="provider-test-fill-2",
        strategy_action_id="strategy-test-action-2",
        side="SELL", quantity=Decimal("2"),
        observed_at_utc=FILL.observed_at_utc + timedelta(seconds=1),
    )
    result = review(fills=(FILL, sell), broker=BASELINE)
    assert result.status == "SHADOW_REVIEW_ONLY"
    assert result.strategy_instrument_count == 0
    assert result.reviewed_fill_count == 2
    assert not result.independent_realized_fills_proven


def test_missing_broker_position_change_blocks_claimed_strategy_fill():
    result = review(fills=(FILL,))
    assert result.status == "BLOCKED"
    assert result.reason == "BROKER_POSITIONS_DO_NOT_MATCH_SHADOW_DELTAS"


def test_unexpected_new_manual_position_cannot_be_marked_strategy():
    other = LegacySimPosition("US.OTHER", "LONG", Decimal("10"))
    result = review(broker=BASELINE + (other,))
    assert result.status == "BLOCKED"
    assert result.reason == "BROKER_POSITIONS_DO_NOT_MATCH_SHADOW_DELTAS"


def test_duplicate_fill_or_action_cannot_inflate_strategy_position():
    dup = replace(FILL, strategy_action_id="strategy-test-action-2")
    assert review(fills=(FILL, dup)).reason == "DUPLICATE_FILL_ID"
    second = replace(FILL, fill_id="provider-test-fill-2")
    assert review(fills=(FILL, second)).reason == "DUPLICATE_STRATEGY_ACTION"


def test_account_symbol_quantity_and_time_mismatches_fail_closed():
    for changes, reason in (
        ({"account_id": "another-account"}, "ACCOUNT_SCOPE_UNKNOWN"),
        ({"fills": (replace(FILL, account_id="999000124"),)}, "FILL_ACCOUNT_MISMATCH"),
        ({"fills": (replace(FILL, symbol="BAD!"),)}, "FILL_INSTRUMENT_OR_SIDE_INVALID"),
        ({"fills": (replace(FILL, quantity=Decimal("NaN")),)}, "FILL_QUANTITY_INVALID"),
        ({"fills": (replace(FILL, observed_at_utc=BEFORE),)},
         "FILL_OUTSIDE_ORDERED_STRATEGY_WINDOW"),
    ):
        result = review(**changes)
        assert result.status == "BLOCKED"
        assert result.reason == reason


def test_private_account_id_and_raw_instruments_not_leaked_in_review_result():
    result = review(fills=(FILL,), broker=updated_amd("1102"))
    serialized = repr(result)
    assert "999000123" not in serialized
    assert "US.AMD" not in serialized
    assert "1102" not in serialized
    assert "SOFA" not in serialized


def test_operator_acceptance_mandatory_and_stale_observations_block():
    assert review(operator_accepted_legacy=False).reason == (
        "LEGACY_INVENTORY_NOT_ACCEPTED"
    )
    result = review(
        baseline_observed_at_utc=NOW - timedelta(minutes=12),
        strategy_started_at_utc=NOW - timedelta(minutes=11),
        current_observed_at_utc=NOW - timedelta(minutes=10),
    )
    assert result.status == "BLOCKED"
    assert result.reason == "BROKER_OBSERVATION_STALE"


def test_legacy_short_book_is_out_of_scope_of_first_long_only_policy():
    baseline = BASELINE + (
        LegacySimPosition("US.XYZ", "SHORT", Decimal("3")),
    )
    assert review(baseline=baseline).reason == (
        "LEGACY_OR_CURRENT_INVENTORY_INVALID"
    )


def test_forged_approval_does_not_create_order_permission():
    result = review(fills=(FILL,), broker=updated_amd("1102"))
    assert result.status == "SHADOW_REVIEW_ONLY"
    assert not result.paper_auto_ready
    assert not result.broker_mutation_allowed
    assert not result.independent_realized_fills_proven
    assert not result.strategy_pnl_eligible
