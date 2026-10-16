"""Explicit TickFlow finality boundary: bar stability is not provider close."""
from datetime import datetime, timedelta, timezone

import pytest

from data_provider.cn_tickflow_research_cache import SCHEMA
from data_provider.tickflow_bar_stability_audit import (
    audit_tickflow_bar_stability,
    audit_tickflow_5m_15m_reconciliation,
)


NOW = datetime(2026, 10, 16, 2, 5, tzinfo=timezone.utc)
SYMBOL = "159611.SZ"
LABEL = "2026-10-16 09:45"
SHA = "a" * 40


def observation(sequence, at):
    row = {
        "label": LABEL,
        "open": 1.03, "high": 1.05, "low": 1.02, "close": 1.04,
        "volume": 12345.0, "amount": 12562.3,
        "amount_availability": "PRESENT_UNVERIFIED",
        "is_partial_bar": True,
        "bar_finality": "NOT_VERIFIED",
        "ohlc_validation": "STRICT",
    }
    return {
        "schema": SCHEMA,
        "provider": "TICKFLOW_PREMIUM",
        "status": "PASS_RESEARCH_ONLY", "repo_sha": SHA,
        "sequence": sequence, "observed_at_utc": at.isoformat(),
        "research_only": True, "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False, "canonical_write_authorized": False,
        "symbols": {SYMBOL: {"15m": {"rows": [row]}}},
    }


def sample_pair():
    return (
        observation(20, NOW - timedelta(seconds=120)),
        observation(21, NOW - timedelta(seconds=70)),
    )


def check(first, second, now=NOW):
    return audit_tickflow_bar_stability(
        first, second, symbol=SYMBOL, timeframe="15m",
        label=LABEL, now_utc=now,
    )


def test_two_stable_matured_polls_are_research_only_not_vendor_final():
    first, second = sample_pair()
    out = check(first, second)
    assert out["status"] == "STABLE_AFTER_MATURITY_NOT_VENDOR_FINAL"
    assert out["two_poll_stable_research_only"] is True
    assert out["bar_clock_matured"] is True
    assert len(out["fingerprint"]) == 16
    assert out["bar_finality"] == "NOT_VERIFIED"
    assert out["exchange_bar_finality"] == "NOT_VERIFIED"
    assert out["provider_finality_attestation"] == (
        "NOT_AVAILABLE_IN_KLINES_SCHEMA"
    )
    assert out["radar_admission"] == "BLOCKED"
    assert out["source_arbiter_admission"] == "BLOCKED"
    assert out["canonical_write_authorized"] is False
    assert out["live_trade"] is False
    assert out["provider_requests"] == 0
    rendered = str(out)
    assert "1.03" not in rendered and "1.04" not in rendered


def test_changed_ohlcv_detected_without_claiming_finality():
    first, second = sample_pair()
    second["symbols"][SYMBOL]["15m"]["rows"][0]["volume"] = 12346.0
    out = check(first, second)
    assert out["status"] == "ROW_MUTATED_AFTER_MATURITY"
    assert out["bar_clock_matured"] is True
    assert out["two_poll_stable_research_only"] is False
    assert out["fingerprint"] is None
    assert out["bar_finality"] == "NOT_VERIFIED"


def test_unchanged_candle_during_first_poll_cannot_qualify():
    first, second = sample_pair()
    first["observed_at_utc"] = datetime(
        2026, 10, 16, 1, 45, 5, tzinfo=timezone.utc,
    ).isoformat()
    second["observed_at_utc"] = datetime(
        2026, 10, 16, 1, 47, tzinfo=timezone.utc,
    ).isoformat()
    out = check(first, second)
    assert out["status"] == "FIRST_POLL_BEFORE_MATURITY"
    assert out["bar_clock_matured"] is False


@pytest.mark.parametrize(("mutate", "expected"), [
    (lambda a, b: a.update(repo_sha="f" * 40), "SOURCE_PROVENANCE_INVALID"),
    (lambda a, b: b.update(provider="TENCENT"), "SOURCE_PROVENANCE_INVALID"),
    (lambda a, b: b.update(research_only=False), "SOURCE_PROVENANCE_INVALID"),
    (lambda a, b: b.update(radar_admission="PASS"), "SOURCE_PROVENANCE_INVALID"),
    (lambda a, b: b.update(sequence=a["sequence"]), "SEQUENCE_NOT_ADVANCING"),
    (lambda a, b: b.update(sequence=True), "SEQUENCE_NOT_ADVANCING"),
    (lambda a, b: b.update(observed_at_utc="bad"), "SOURCE_PROVENANCE_INVALID"),
    (lambda a, b: b["symbols"][SYMBOL]["15m"]["rows"][0].update(
        bar_finality="PROVEN"
    ), "BAR_NOT_OBSERVED_OR_UNSAFE"),
    (lambda a, b: b["symbols"][SYMBOL]["15m"]["rows"][0].update(
        is_partial_bar=False
    ), "BAR_NOT_OBSERVED_OR_UNSAFE"),
    (lambda a, b: b["symbols"][SYMBOL]["15m"]["rows"][0].update(
        high=0.95
    ), "BAR_NOT_OBSERVED_OR_UNSAFE"),
    (lambda a, b: b["symbols"][SYMBOL]["15m"]["rows"][0].update(
        close=float("nan")
    ), "BAR_NOT_OBSERVED_OR_UNSAFE"),
    (lambda a, b: b["symbols"][SYMBOL]["15m"]["rows"][0].update(
        close=10 ** 999
    ), "BAR_NOT_OBSERVED_OR_UNSAFE"),
])
def test_untrusted_provenance_or_bar_shape_blocks(mutate, expected):
    first, second = sample_pair()
    mutate(first, second)
    assert check(first, second)["status"] == expected


def test_same_cached_publication_or_stale_poll_is_not_two_observations():
    first, second = sample_pair()
    second["observed_at_utc"] = first["observed_at_utc"]
    assert check(first, second)["status"] == "POLL_LINEAGE_INVALID"

    first, second = sample_pair()
    assert check(first, second, NOW + timedelta(minutes=10))["status"] == (
        "POLL_LINEAGE_INVALID"
    )


def test_source_supplied_untrusted_close_flags_never_upgrade_gate():
    first, second = sample_pair()
    second["symbols"][SYMBOL]["15m"]["rows"][0]["exchange_closed"] = True
    second["symbols"][SYMBOL]["15m"]["rows"][0]["provider_finality"] = "PASS"
    # Unknown booleans are *not* an authorized provider finality contract.
    verdict = check(first, second)
    assert verdict["bar_finality"] == "NOT_VERIFIED"
    assert verdict["radar_admission"] == "BLOCKED"


def test_invalid_boundary_including_daily_and_off_grid_is_rejected():
    first, second = sample_pair()
    for symbol, timeframe, label in (
        ("159611.SZ", "1d", LABEL),
        ("600000.SH", "15m", LABEL),
        (SYMBOL, "15m", "2026-10-16 09:47"),
        (SYMBOL, "15m", "2026-10-16 11:00"),
    ):
        verdict = audit_tickflow_bar_stability(
            first, second, symbol=symbol, timeframe=timeframe,
            label=label, now_utc=NOW,
        )
        assert verdict["two_poll_stable_research_only"] is False
        assert verdict["radar_admission"] == "BLOCKED"


def multi_period_fixture():
    snap = observation(100, NOW - timedelta(seconds=7))
    snap["symbols"][SYMBOL]["5m"] = {
        "rows": [
            {
                "label": "2026-10-16 09:35", "open": 1.03,
                "high": 1.04, "low": 1.02, "close": 1.035,
                "volume": 4000, "amount": 4000.0,
                "bar_finality": "NOT_VERIFIED",
                "is_partial_bar": True, "ohlc_validation": "STRICT",
            },
            {
                "label": "2026-10-16 09:40", "open": 1.035,
                "high": 1.05, "low": 1.03, "close": 1.045,
                "volume": 5000, "amount": 5500.0,
                "bar_finality": "NOT_VERIFIED",
                "is_partial_bar": True, "ohlc_validation": "STRICT",
            },
            {
                "label": "2026-10-16 09:45", "open": 1.045,
                "high": 1.049, "low": 1.04, "close": 1.04,
                "volume": 3345, "amount": 3062.3,
                "bar_finality": "NOT_VERIFIED",
                "is_partial_bar": True, "ohlc_validation": "STRICT",
            },
        ],
    }
    return snap


def reconcile(snap):
    return audit_tickflow_5m_15m_reconciliation(
        snap, symbol=SYMBOL, label=LABEL, now_utc=NOW,
    )


def test_three_5m_bars_reconstruct_vendor_15m_but_never_finality():
    snap = multi_period_fixture()
    got = reconcile(snap)
    assert got["status"] == "OHLCVA_AGGREGATION_RESEARCH_MATCH"
    assert got["provider_requests"] == 0
    assert got["bar_finality"] == "NOT_VERIFIED"
    assert got["radar_admission"] == "BLOCKED"
    assert got["live_trade"] is False


@pytest.mark.parametrize(("edit", "expected"), [
    (lambda x: x["symbols"][SYMBOL]["5m"]["rows"][1].update(
        volume=5001
    ), "OHLCV_DIVERGENCE"),
    (lambda x: x["symbols"][SYMBOL]["5m"]["rows"][2].update(
        close=1.041
    ), "OHLCV_DIVERGENCE"),
    (lambda x: x["symbols"][SYMBOL]["5m"]["rows"][1].update(
        amount=5501.0
    ), "AMOUNT_DIVERGENCE"),
    (lambda x: x["symbols"][SYMBOL]["5m"]["rows"][1].update(
        is_partial_bar=False
    ), "RECONCILIATION_ROWS_MISSING_OR_UNSAFE"),
    (lambda x: x["symbols"][SYMBOL]["5m"]["rows"][1].update(
        ohlc_validation="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    ), "RECONCILIATION_ROWS_MISSING_OR_UNSAFE"),
    (lambda x: x["symbols"][SYMBOL]["5m"]["rows"][1].update(
        amount=None
    ), "OHLCV_MATCH_AMOUNT_NOT_AVAILABLE"),
    (lambda x: x["symbols"][SYMBOL]["5m"]["rows"].pop(),
     "RECONCILIATION_ROWS_MISSING_OR_UNSAFE"),
    (lambda x: x.update(provider="TENCENT"), "SOURCE_PROVENANCE_INVALID"),
    (lambda x: x.update(radar_admission="PASS"),
     "SOURCE_PROVENANCE_INVALID"),
])
def test_reconciliation_never_promotes_invalid_rows(edit, expected):
    snap = multi_period_fixture()
    edit(snap)
    got = reconcile(snap)
    assert got["status"] == expected
    assert got["bar_finality"] == "NOT_VERIFIED"
    assert got["radar_admission"] == "BLOCKED"


def test_reconciliation_does_not_accept_before_expected_bar_clock():
    snap = multi_period_fixture()
    result = audit_tickflow_5m_15m_reconciliation(
        snap, symbol=SYMBOL, label=LABEL,
        now_utc=datetime(2026, 10, 16, 1, 45, tzinfo=timezone.utc),
    )
    assert result["status"] == "BOUNDARY_NOT_MATURE"
    assert result["live_trade"] is False


def test_missing_turnover_cannot_be_called_complete_bar_stability():
    first, second = sample_pair()
    first["symbols"][SYMBOL]["15m"]["rows"][0]["amount"] = None
    second["symbols"][SYMBOL]["15m"]["rows"][0]["amount"] = None
    result = check(first, second)
    assert result["status"] == "AMOUNT_NOT_AVAILABLE_FOR_STABILITY"
    assert result["two_poll_stable_research_only"] is False
    assert result["fingerprint"] is None
    assert result["bar_finality"] == "NOT_VERIFIED"


def test_aggregation_rejects_provider_snapshot_observed_before_bar_maturity():
    snapshot = multi_period_fixture()
    snapshot["observed_at_utc"] = datetime(
        2026, 10, 16, 1, 45, 20, tzinfo=timezone.utc,
    ).isoformat()
    result = audit_tickflow_5m_15m_reconciliation(
        snapshot, symbol=SYMBOL, label=LABEL,
        now_utc=datetime(2026, 10, 16, 1, 47, 0, tzinfo=timezone.utc),
    )
    assert result["status"] == "SOURCE_OBSERVED_BEFORE_MATURITY"
    assert result["bar_finality"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"


def test_weekend_bar_label_is_not_exchange_session_evidence():
    first, second = sample_pair()
    bad_label = "2026-10-17 09:45"  # Saturday in Shanghai
    later = datetime(2026, 10, 18, 2, 5, tzinfo=timezone.utc)
    stability = audit_tickflow_bar_stability(
        first, second, symbol=SYMBOL, timeframe="15m",
        label=bad_label, now_utc=later,
    )
    aggregation = audit_tickflow_5m_15m_reconciliation(
        second, symbol=SYMBOL, label=bad_label, now_utc=later,
    )
    assert stability["status"] == "NON_TRADING_WEEKDAY"
    assert aggregation["status"] == "NON_TRADING_WEEKDAY"
    assert stability["radar_admission"] == "BLOCKED"
    assert aggregation["exchange_bar_finality"] == "NOT_VERIFIED"
