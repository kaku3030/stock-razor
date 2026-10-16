"""Proof that TickFlow research stability never impersonates finality."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from data_provider.tickflow_bar_close_witness import audit_repeated_tickflow_bar


SHA = "a" * 40
SYMBOL = "159611.SZ"
BAR = "2026-10-16 09:45"
NEXT = "2026-10-16 10:00"
NOW = datetime(2026, 10, 16, 2, 3, tzinfo=timezone.utc)


def _bar(label, price=1.045):
    return {
        "label": label, "open": price, "high": price + .001,
        "low": price - .001, "close": price, "volume": 1100,
        "amount": 1180, "amount_availability": "PRESENT_UNVERIFIED",
        "ohlc_validation": "STRICT", "bar_finality": "NOT_VERIFIED",
        "is_partial_bar": True,
    }


def _snapshot(seq, at, *, next_visible=False):
    rows = [_bar(BAR)]
    if next_visible:
        rows.append(_bar(NEXT, 1.046))
    return {
        "schema": "stock_razor_cn_tickflow_research_observation_v0_1",
        "provider": "TICKFLOW_PREMIUM",
        "status": "PASS_RESEARCH_ONLY",
        "repo_sha": SHA,
        "observed_at_utc": at,
        "sequence": seq,
        "research_only": True,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
        "can_confirm_signal": False,
        "canonical_write_authorized": False,
        "symbols": {SYMBOL: {
            "15m": {
                "closure": "NOT_VERIFIED", "currentness": "UNPROVEN",
                "rows": rows,
            },
        }},
    }


def _pair():
    return (
        _snapshot(101, "2026-10-16T02:01:00+00:00"),
        _snapshot(102, "2026-10-16T02:02:45+00:00",
                  next_visible=True),
    )


def _audit(first=None, second=None, **kw):
    if first is None or second is None:
        f, s = _pair()
        first = f if first is None else first
        second = s if second is None else second
    return audit_repeated_tickflow_bar(
        first, second, symbol=SYMBOL, timeframe="15m",
        bar_end_label=BAR, now_utc=NOW, **kw,
    )


def test_two_independent_polls_and_next_bar_only_prove_research_stability():
    result = _audit()
    assert result["status"] == "STABLE_AFTER_NEXT_LABEL_RESEARCH_ONLY"
    assert result["bar_label_stability"] == "REPEATED_OHLCVA_RESEARCH_ONLY"
    assert result["poll_gap_seconds"] == 105.0
    assert result["provider_bar_finality"] == "NOT_VERIFIED"
    assert result["exchange_bar_finality"] == "NOT_VERIFIED"
    assert result["trading_session_calendar"] == "NOT_VERIFIED"
    assert result["provider_requests"] == 0
    assert result["radar_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["paper_auto_ready"] is False
    assert result["live_trade"] is False
    assert "1.045" not in repr(result)
    assert BAR not in repr(result)


@pytest.mark.parametrize("modify,reason", [
    (lambda f, s: s["symbols"][SYMBOL]["15m"]["rows"][0].update(
        close=1.055,
    ), "BAR_REVISED_BETWEEN_POLLS"),
    (lambda f, s: s.update(repo_sha="b" * 40), "SOURCE_SHA_CHANGED"),
    (lambda f, s: s.update(sequence=101), "INDEPENDENT_POLL_NOT_PROVEN"),
    (lambda f, s: s.update(sequence=99), "INDEPENDENT_POLL_NOT_PROVEN"),
    (lambda f, s: s.update(
        observed_at_utc="2026-10-16T02:01:00+00:00",
    ), "INDEPENDENT_POLL_NOT_PROVEN"),
    (lambda f, s: s.update(
        observed_at_utc="2026-10-16T02:04:00+00:00",
    ), "LATEST_SOURCE_STALE_OR_FUTURE"),
    (lambda f, s: s["symbols"][SYMBOL]["15m"]["rows"].pop(),
     "CLOSED_GRID_DATA_INCOMPLETE"),
    (lambda f, s: s["symbols"][SYMBOL]["15m"]["rows"][0].update(
        is_partial_bar=False,
    ), "CLOSED_GRID_DATA_INCOMPLETE"),
    (lambda f, s: s["symbols"][SYMBOL]["15m"]["rows"][0].update(
        bar_finality="PROVIDER_CONFIRMED",
    ), "CLOSED_GRID_DATA_INCOMPLETE"),
    (lambda f, s: s.update(radar_admission="PASS"),
     "UNTRUSTED_RESEARCH_SNAPSHOT"),
    (lambda f, s: s.update(provider="EASTMONEY"),
     "UNTRUSTED_RESEARCH_SNAPSHOT"),
    (lambda f, s: s["symbols"][SYMBOL]["15m"]["rows"][0].update(
        volume=float("nan"),
    ), "CLOSED_GRID_DATA_INCOMPLETE"),
    (lambda f, s: s["symbols"][SYMBOL]["15m"]["rows"][0].update(
        amount="secret",
    ), "CLOSED_GRID_DATA_INCOMPLETE"),
])
def test_fails_closed_for_revised_stale_untrusted_and_malformed_evidence(
    modify, reason,
):
    first, second = _pair()
    modify(first, second)
    result = _audit(first, second)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == reason
    assert result["provider_bar_finality"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"


def test_next_bar_needs_time_to_mature():
    first, second = _pair()
    before_grace = audit_repeated_tickflow_bar(
        first, second, symbol=SYMBOL, timeframe="15m",
        bar_end_label=BAR,
        now_utc=datetime(2026, 10, 16, 2, 1, tzinfo=timezone.utc),
    )
    assert before_grace["reason"] == "NEXT_GRID_NOT_MATURED"


def test_missing_next_bar_does_not_prove_stability():
    first, second = _pair()
    second["symbols"][SYMBOL]["15m"]["rows"] = [_bar(BAR)]
    result = _audit(first, second)
    assert result["reason"] == "CLOSED_GRID_DATA_INCOMPLETE"


def test_wrong_clock_period_symbol_and_missing_next_grid_fail():
    first, second = _pair()
    params = dict(first=first, second=second, symbol=SYMBOL,
                  timeframe="15m", bar_end_label=BAR, now_utc=NOW)
    for changes in (
        {"timeframe": "1d"}, {"symbol": "512730.SH"},
        {"bar_end_label": "2026-10-16 10:01"},
        {"bar_end_label": "2026-10-16 15:00"},
        {"min_poll_gap_seconds": 0},
        {"now_utc": NOW.replace(tzinfo=None)},
    ):
        assert audit_repeated_tickflow_bar(
            **(params | changes)
        )["status"] == "BLOCKED"


def test_no_invented_source_finality_on_replay_or_identical_rows():
    first, second = _pair()
    same = deepcopy(second)
    same["sequence"] += 1
    witness = _audit(second, same)
    assert witness["provider_bar_finality"] == "NOT_VERIFIED"
    assert witness["status"] == "BLOCKED"
