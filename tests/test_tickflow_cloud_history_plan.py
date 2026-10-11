"""Zero paid requests regardless of the evidence flags."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from data_provider.tickflow_cloud_history_plan import (
    TickFlowHistoryPilot, review_tickflow_pilot,
)

NOW = datetime(2026, 10, 11, 13, tzinfo=timezone.utc)
PILOT = TickFlowHistoryPilot(
    ("159611.SZ", "512730.SH"), NOW-timedelta(days=2),
    NOW-timedelta(days=1), "15m",
)


def review(pilot=PILOT, **updates):
    opts = dict(
        account_entitlement_verified=True,
        billing_units_verified=True,
        request_charge_ceiling_approved=True,
    )
    opts.update(updates)
    return review_tickflow_pilot(pilot, now_utc=NOW, **opts)


def test_no_confirmation_defaults_to_blocked_and_zero_network():
    result = review_tickflow_pilot(PILOT, now_utc=NOW)
    assert result.status == "BLOCKED"
    assert result.reason == "ACCOUNT_ENTITLEMENT_UNVERIFIED"
    assert result.provider_calls == result.ledger_reservations == 0


def test_even_verified_one_call_plan_has_no_execution_authority():
    result = review()
    assert result.status == "REVIEW_ONLY"
    assert result.planned_request_ceiling == 1
    assert result.symbol_count == 2
    assert result.provider_calls == 0
    assert result.source_arbiter_admission == "BLOCKED"
    assert not result.paper_auto_ready and not result.live_trade


def test_missing_billing_or_explicit_charge_approval_blocks():
    assert review(billing_units_verified=False).reason == "BILLING_UNITS_UNVERIFIED"
    assert review(request_charge_ceiling_approved=False).reason == "PAID_REQUEST_NOT_APPROVED"


def test_reject_history_outside_maximum_and_multi_day_pilot():
    assert review(replace(
        PILOT, start_utc=NOW-timedelta(days=367)
    )).reason == "WINDOW_OUTSIDE_ENTITLEMENT"
    assert review(replace(
        PILOT, start_utc=NOW-timedelta(days=10),
        end_utc=NOW-timedelta(days=8),
    )).reason == "PILOT_WINDOW_MORE_THAN_ONE_DAY"


def test_reject_invalid_etf_symbols_and_duplicate_keys():
    for syms in ((), ("159611.SZ", "159611.SZ"), ("NOT_A_SYMBOL",),
                 ("159611.SZ ",), tuple(f"{i:06d}.SZ" for i in range(6))):
        assert review(replace(PILOT, symbols=syms)).status == "BLOCKED"


def test_minute_only_and_single_request_ceiling():
    assert review(replace(PILOT, timeframe="1d")).reason == "PILOT_TIMEFRAME_UNSUPPORTED"
    assert review(replace(
        PILOT, max_provider_requests=2
    )).reason == "PILOT_MAX_REQUESTS_NOT_ONE"
