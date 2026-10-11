"""Reproducible offline bridge: cloud bar API-shaped data, no broker fills."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.closed_bar_paper_replay import HistoricalEntryBand
from src.services.us_offline_cloud_replay_batch import (
    HistoricalReplayDecision, run_offline_cloud_replay_batch,
)

START = datetime(2026, 10, 9, 13, 30, tzinfo=timezone.utc)


def payload(timeframe="15m"):
    bars = []
    if timeframe == "15m":
        for i in range(26):
            begin = START + timedelta(minutes=i * 15)
            end = begin + timedelta(minutes=15)
            bars.append(dict(
                symbol="US.AMD", market="us", asset_type="stock",
                timeframe="15m", session="regular", provider="futu",
                feed="opend", bar_start_utc=begin.isoformat(),
                bar_end_utc=end.isoformat(),
                source_timestamp_utc=end.isoformat(),
                received_at_utc=(end + timedelta(days=1)).isoformat(),
                open="100", high="101", low="99", close="100", volume=1000,
                quality_flags=["HISTORICAL_QUERY", "STALE"],
                is_closed=True, is_complete=True,
            ))
    else:
        for i in range(7):
            begin = START + timedelta(hours=i)
            end = begin + timedelta(minutes=30 if i == 6 else 60)
            bars.append(dict(
                symbol="US.AMD", market="us", asset_type="stock",
                timeframe="1h", session="regular", provider="futu",
                feed="opend", bar_start_utc=begin.isoformat(),
                bar_end_utc=end.isoformat(),
                source_timestamp_utc=end.isoformat(),
                received_at_utc=(end + timedelta(days=1)).isoformat(),
                quality_flags=["HISTORICAL_QUERY", "STALE"],
                is_closed=True, is_complete=True,
            ))
    return {"ok": True, "status": "STALE", "bars": bars}


def decision(index=3, *, id="obs-1", hourly=True, band=None):
    return HistoricalReplayDecision(
        id, "AMD", START + timedelta(minutes=15 * (index + 1)),
        band or HistoricalEntryBand(
            low=Decimal("99"), high=Decimal("101"),
            stop=Decimal("98"), target=Decimal("103"),
            round_trip_fee_per_share=Decimal("0.02"),
        ), hourly,
    )


def test_actual_public_shape_replay_bridges_all_three_modules_without_broker():
    quote15, quote60 = payload("15m"), payload("1h")
    # First full 60m close is 14:30 UTC, next 15m open is 14:30 UTC.
    quote15["bars"][6].update(high="104", close="102")
    result = run_offline_cloud_replay_batch(
        quote15, quote60, symbol="AMD", decisions=(decision(3),),
    )
    assert result.session_count == 1
    assert result.requested_count == 1
    assert result.hypothetical_result_count == 1
    assert result.no_fill_count == 0
    assert result.blocked_count == 0
    assert result.records[0].receipt.exit_reason == "TARGET"
    assert result.hypothetical_total_r == (Decimal("103") - Decimal("100") - Decimal("0.02")) / Decimal("2")
    assert result.hypothetical_average_r == result.hypothetical_total_r
    assert result.realized_r_not_available is True
    assert result.actual_moomoo_simulator_used is False
    assert result.external_order_ids_verified is False
    assert result.paper_auto_ready is False
    assert result.live_trade is False
    assert result.radar_admission == "BLOCKED"
    assert result.same_provider_source_independence_verified is False


def test_missing_full_hour_for_early_bar_blocks_without_mutation():
    result = run_offline_cloud_replay_batch(
        payload("15m"), payload("1h"), symbol="AMD",
        decisions=(decision(0),),
    )
    assert result.hypothetical_result_count == 0
    assert result.blocked_count == 1
    assert result.records[0].receipt.reason == "60M_SOURCE_NOT_QUALIFIED"
    assert result.hypothetical_average_r is None


def test_signal_at_final_closed_bar_cannot_place_next_day_open_order():
    result = run_offline_cloud_replay_batch(
        payload("15m"), payload("1h"), symbol="AMD",
        decisions=(decision(25),),
    )
    assert result.blocked_count == 1
    assert result.records[0].receipt.reason == "NEXT_15M_OPEN_UNAVAILABLE"


def test_next_open_outside_plan_band_is_not_a_fill():
    quote15 = payload()
    quote15["bars"][4].update(open="105", high="106", low="104", close="105")
    result = run_offline_cloud_replay_batch(
        quote15, payload("1h"), symbol="AMD",
        decisions=(decision(3),),
    )
    assert result.no_fill_count == 1
    assert result.hypothetical_result_count == 0
    assert result.records[0].receipt.reason == "NEXT_OPEN_OUTSIDE_ENTRY_BAND"


def test_false_hourly_gate_is_a_block_not_a_missing_order():
    result = run_offline_cloud_replay_batch(
        payload(), payload("1h"), symbol="AMD",
        decisions=(decision(3, hourly=False),),
    )
    assert result.blocked_count == 1
    assert result.records[0].receipt.reason == "60M_GATE_NOT_PIT_QUALIFIED"


def test_invalid_hour_source_cannot_be_laundered_into_paper():
    hours = payload("1h")
    hours["bars"][0]["feed"] = "unreviewed"
    result = run_offline_cloud_replay_batch(
        payload(), hours, symbol="AMD", decisions=(decision(3),),
    )
    assert result.blocked_count == 1
    assert result.records[0].receipt.reason == "60M_SOURCE_NOT_QUALIFIED"


def test_timestamp_missing_or_wrong_symbol_never_creates_synthetic_fill():
    case = decision(3)
    changed = HistoricalReplayDecision(
        "later", "AMD", case.closed_signal_at + timedelta(seconds=1),
        case.entry, True,
    )
    result = run_offline_cloud_replay_batch(
        payload(), payload("1h"), symbol="AMD", decisions=(changed,),
    )
    assert result.blocked_count == 1
    assert result.records[0].receipt.reason == "SIGNAL_CLOSED_BAR_MISSING_OR_DUPLICATE"
    with pytest.raises(ValueError, match="CROSS_SYMBOL"):
        run_offline_cloud_replay_batch(
            payload(), payload("1h"), symbol="AMD",
            decisions=(HistoricalReplayDecision("other", "AAPL", case.closed_signal_at, case.entry, True),),
        )


def test_no_duplicate_obs_or_unbounded_batch_allowed():
    one = decision()
    for values in ((), (one, one), (one,) * 65):
        with pytest.raises(ValueError):
            run_offline_cloud_replay_batch(
                payload(), payload("1h"), symbol="AMD", decisions=values,
            )


def test_input_flags_not_truthy_strings_and_id_secrets_rejected():
    with pytest.raises(ValueError, match="REPLAY_DECISION_FIELDS_INVALID"):
        HistoricalReplayDecision("id", "AMD", decision().closed_signal_at, decision().entry, "true")
    with pytest.raises(ValueError, match="OBSERVATION_ID_INVALID"):
        HistoricalReplayDecision("obs/password=secret", "AMD", decision().closed_signal_at, decision().entry, True)


def test_incomplete_or_wrong_market_data_blocks_whole_batch():
    source = payload()
    source["bars"] = source["bars"][:-1]
    with pytest.raises(ValueError):
        run_offline_cloud_replay_batch(
            source, payload("1h"), symbol="AMD", decisions=(decision(),),
        )


def test_stop_target_collision_is_assumed_stop_first_through_entire_batch():
    data = payload()
    # Both stop and target may be touched after the entry open; 15m bars
    # cannot resolve intrabar ordering. No hindsight selection of target.
    data["bars"][4].update(open="100", low="97", high="105", close="101")
    r = run_offline_cloud_replay_batch(
        data, payload("1h"), symbol="AMD", decisions=(decision(3),),
    )
    assert r.hypothetical_result_count == 1
    assert r.records[0].receipt.exit_reason == "STOP_FIRST_AMBIGUOUS"
    assert r.hypothetical_total_r < Decimal("-1")


def test_gapped_stop_uses_adverse_next_bar_open_not_plan_stop():
    data = payload()
    # Entry on bar 4 at 100, then bar 5 gaps from 100 to 95; fill at 95.
    data["bars"][5].update(open="95", low="94", high="98", close="96")
    r = run_offline_cloud_replay_batch(
        data, payload("1h"), symbol="AMD", decisions=(decision(3),),
    )
    assert r.records[0].receipt.exit_reason == "STOP_GAP_OPEN"
    assert r.records[0].receipt.exit == Decimal("95")
    assert r.hypothetical_total_r < Decimal("-1")


def test_mixed_blocked_and_filled_are_counted_without_promoting_paper():
    r = run_offline_cloud_replay_batch(
        payload(), payload("1h"), symbol="AMD",
        decisions=(decision(0, id="early"), decision(3, id="valid"),
                   decision(25, id="late")),
    )
    assert r.requested_count == 3
    assert r.blocked_count == 2
    assert r.hypothetical_result_count == 1
    assert r.no_fill_count == 0
    assert r.paper_auto_ready is False
    assert r.external_order_ids_verified is False
