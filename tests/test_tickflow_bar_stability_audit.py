"""Explicit TickFlow finality boundary: bar stability is not provider close."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from data_provider.cn_tickflow_research_cache import SCHEMA
from data_provider.tickflow_bar_stability_audit import audit_tickflow_bar_stability


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
