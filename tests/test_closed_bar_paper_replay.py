"""Deterministic bar replay is never a broker Paper execution receipt."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.closed_bar_paper_replay import (
    Closed15mBar, HistoricalEntryBand, UpstreamHourlyGate, replay_closed_bar_long,
)

START = datetime(2026, 10, 9, 13, 30, tzinfo=timezone.utc)


def bar(i=0, *, o="100", h="101", l="99", c="100", source="futu", closed=True):
    a = START + timedelta(minutes=i * 15)
    return Closed15mBar(
        a, a + timedelta(minutes=15),
        Decimal(o), Decimal(h), Decimal(l), Decimal(c),
        Decimal("100"), source, closed,
    )


def gate(**kw):
    defaults = dict(closed_bar_end=START, passed=True, bar_was_closed=True, source="futu")
    defaults.update(kw)
    return UpstreamHourlyGate(**defaults)


def plan(**kw):
    defaults = dict(
        low=Decimal("100"), high=Decimal("102"),
        stop=Decimal("98"), target=Decimal("104"),
        entry_slippage_per_share=Decimal("0.1"),
        exit_slippage_per_share=Decimal("0.2"),
        round_trip_fee_per_share=Decimal("0.02"),
    )
    defaults.update(kw)
    return HistoricalEntryBand(**defaults)


def test_closed_hourly_signal_enters_only_on_next_bar_open_and_exits_target():
    rows = (bar(0), bar(1, o="100", h="104.5", l="99", c="103"), bar(2))
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.status == "HYPOTHETICAL_CLOSED_BAR_RESULT"
    assert r.decision_as_of == START + timedelta(minutes=15)
    assert r.hypothetical_entry_at == START + timedelta(minutes=15)
    assert r.entry == Decimal("100.1")
    assert r.exit == Decimal("103.8")
    assert r.risk_per_share == Decimal("2.1")
    assert r.net_r == (Decimal("103.8")-Decimal("100.1")-Decimal("0.02"))/Decimal("2.1")
    assert r.exit_reason == "TARGET"
    assert r.research_only is True
    assert r.external_simulator_verified is False
    assert r.broker_paper_order_submitted is False
    assert r.paper_auto_ready is False
    assert r.radar_admission == "BLOCKED"
    assert r.live_trade is False


def test_when_same_bar_hits_stop_and_target_stop_wins():
    rows = (bar(0), bar(1, o="100", h="105", l="97", c="103"))
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.exit_reason == "STOP_FIRST_AMBIGUOUS"
    assert r.exit == Decimal("97.8")
    assert r.net_r < Decimal("-1")


def test_next_open_gap_outside_entry_band_has_no_fill():
    rows = (bar(0), bar(1, o="104", h="105", l="103", c="104"))
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.status == "NO_FILL"
    assert r.net_r is None
    assert r.broker_paper_order_submitted is False


def test_overnight_missing_bars_and_duplicates_block_without_fill():
    rows = (bar(0), bar(2))
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.reason == "BAR_GAP_OR_DUPLICATE"
    duplicate = (bar(0), bar(0))
    assert replay_closed_bar_long(duplicate, decision_index=0, hourly=gate(), entry=plan()).reason == "BAR_GAP_OR_DUPLICATE"


def test_future_or_unclosed_or_stale_hour_cannot_launder_lookahead():
    rows = (bar(0), bar(1))
    for evidence in (
        gate(closed_bar_end=START+timedelta(minutes=60)),
        gate(closed_bar_end=START-timedelta(minutes=120)),
        gate(bar_was_closed=False),
        gate(bar_duration_minutes=30),  # The last RTH \"1h\" candle is only 30m.
        gate(passed=False),
        gate(source="other-provider"),
    ):
        r = replay_closed_bar_long(rows, decision_index=0, hourly=evidence, entry=plan())
        assert r.status == "BLOCKED"
        assert r.reason == "60M_GATE_NOT_PIT_QUALIFIED"


def test_explicitly_unclosed_signal_or_outcome_blocks():
    rows = (bar(0), bar(1, closed=False))
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.reason == "UNCLOSED_15M_BAR"


def test_broker_source_switch_blocked_and_last_bar_cannot_enter():
    rows = (bar(0), bar(1, source="unknown"))
    assert replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan()).reason == "MIXED_PROVIDER"
    rows = (bar(0), bar(1))
    assert replay_closed_bar_long(rows, decision_index=1, hourly=gate(), entry=plan()).reason == "NEXT_15M_OPEN_UNAVAILABLE"


def test_negative_and_nonfinite_ohlc_and_costs_are_rejected():
    with pytest.raises(ValueError):
        bar(0, h="NaN")
    with pytest.raises(ValueError):
        bar(0, l="101", h="102")
    with pytest.raises(ValueError):
        plan(entry_slippage_per_share=Decimal("-1"))
    with pytest.raises(ValueError):
        plan(stop=Decimal("100"))
    with pytest.raises(ValueError):
        plan(target=Decimal("101"))
    with pytest.raises(ValueError):
        bar(0, o="Infinity")


def test_end_of_day_exits_with_per_share_costs_not_broker_fills():
    rows = (bar(0), bar(1, o="100", h="101", l="99", c="101"))
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.exit_reason == "EOD_CLOSE"
    assert r.exit == Decimal("100.8")
    assert r.net_r == Decimal("0.68") / Decimal("2.1")
    assert r.future_bars_are_outcome_only is True


def test_stopped_at_open_after_entry_uses_worse_gap_price():
    rows = (bar(0), bar(1, o="100", h="101", l="99", c="100"),
            bar(2, o="96", h="99", l="95", c="97"))
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.exit_reason == "STOP_GAP_OPEN"
    assert r.exit == Decimal("95.8")
    assert r.net_r < Decimal("-1")


def test_no_future_day_can_be_treated_as_continuous_rth_sequence():
    rows = (bar(0), replace(bar(1), start=START + timedelta(days=1),
                            end=START + timedelta(days=1, minutes=15)))
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.status == "BLOCKED"
    assert r.reason == "CROSSES_UTC_SESSION_DAY"


def test_invalid_signal_and_empty_series_fail_closed():
    assert replay_closed_bar_long((), decision_index=0, hourly=gate(), entry=plan()).status == "BLOCKED"
    assert replay_closed_bar_long((bar(0),), decision_index=True, hourly=gate(), entry=plan()).reason == "DECISION_INDEX_INVALID"


def test_false_like_or_ambiguous_bar_closure_flag_is_invalid():
    with pytest.raises(ValueError, match="BAR_CLOSURE_PROOF_INVALID"):
        bar(0, closed="false")


def test_contiguous_cross_midnight_series_still_blocks_as_single_day_research():
    a = datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc)
    rows = (
        Closed15mBar(a, a + timedelta(minutes=15), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("10"), "futu"),
        Closed15mBar(a + timedelta(minutes=15), a + timedelta(minutes=30), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("10"), "futu"),
        Closed15mBar(a + timedelta(minutes=30), a + timedelta(minutes=45), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("10"), "futu"),
    )
    r = replay_closed_bar_long(rows, decision_index=0, hourly=gate(), entry=plan())
    assert r.status == "BLOCKED"
    assert r.reason == "CROSSES_UTC_SESSION_DAY"


def test_last_30m_of_us_rth_is_not_mislabeled_full_60m_confirmation():
    # Historical Futu "1h" has 6 full 60m candles + a final 30m candle.
    rows = (bar(0), bar(1))
    evidence = gate(bar_duration_minutes=30)
    r = replay_closed_bar_long(rows, decision_index=0, hourly=evidence, entry=plan())
    assert r.status == "BLOCKED"
    assert r.reason == "60M_GATE_NOT_PIT_QUALIFIED"
    assert r.broker_paper_order_submitted is False
