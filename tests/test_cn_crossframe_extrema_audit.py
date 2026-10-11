from decimal import Decimal
from dataclasses import replace

import pytest

from src.services.cn_crossframe_extrema_audit import (
    CN_15M_END_LABELS,
    audit_cn_15m_against_daily,
)

DAY = "2026-09-28"


def mk_fixture():
    rows = [
        {"label": f"{DAY} {label}", "provider": "tencent", "volume_unit": "HAND",
         "open": Decimal("1.2"), "close": Decimal("1.2"),
         "high": Decimal("1.21"), "low": Decimal("1.19"), "volume_raw": 100}
        for label in CN_15M_END_LABELS
    ]
    d = {"label": DAY, "provider": "tencent", "volume_unit": "HAND",
         "open": Decimal("1.2"), "close": Decimal("1.2"),
         "high": Decimal("1.21"), "low": Decimal("1.19"), "volume_raw": 1600}
    return d, rows


def test_matching_16x15m_tencent_session_is_only_offline_consistency():
    d, rows = mk_fixture()
    r = audit_cn_15m_against_daily(d, rows)
    assert r.status == "MATCHED_OFFLINE_ONLY"
    assert r.reasons == ()
    assert r.high_gap == r.low_gap == r.volume_gap == 0
    assert r.independent_source_verified is False
    assert r.intraday_currentness_verified is False
    assert r.auction_coverage_verified is False
    assert r.signal_confirmation_allowed is False
    assert r.broker_io_performed is False
    assert r.live_trade is False


def test_actual_159363_sep28_extrema_mismatch_exposed_not_assumed_bad_provider():
    d, rows = mk_fixture()
    d["high"] = Decimal("1.246")
    rows[0]["high"] = Decimal("1.239")
    for x in rows[1:]:
        x["high"] = Decimal("1.238")
    r = audit_cn_15m_against_daily(d, rows)
    assert r.status == "DIVERGENT_OR_INCOMPLETE"
    assert r.high_gap == Decimal("0.007")
    assert r.reasons == ("DAILY_HIGH_NOT_RECONCILED",)
    assert r.auction_coverage_verified is False
    assert r.signal_confirmation_allowed is False


def test_missing_or_duplicate_15m_boundary_cannot_be_complete():
    d, rows = mk_fixture()
    for bad in (rows[:-1], [rows[0], *rows[:-1]]):
        r = audit_cn_15m_against_daily(d, bad)
        assert r.status == "DIVERGENT_OR_INCOMPLETE"
        assert any("SESSION" in reason for reason in r.reasons)


def test_different_provider_unknown_lineage_and_units_are_visible():
    d, rows = mk_fixture()
    rows[0]["provider"] = "eastmoney"
    rows[0]["volume_unit"] = "SHARE"
    r = audit_cn_15m_against_daily(d, rows)
    assert "CROSS_PROVIDER_LINEAGE_UNKNOWN" in r.reasons
    assert "VOLUME_UNIT_MISMATCH" in r.reasons


def test_volume_tolerance_accounts_for_fractional_hand_rounding():
    d, rows = mk_fixture()
    rows[0]["volume_raw"] = Decimal("99.6")
    r = audit_cn_15m_against_daily(d, rows)
    assert r.status == "MATCHED_OFFLINE_ONLY"
    rows[1]["volume_raw"] = Decimal("98.5")
    r = audit_cn_15m_against_daily(d, rows)
    assert "SESSION_VOLUME_DIVERGENCE" in r.reasons


@pytest.mark.parametrize("bad", ["nan", "inf", -1, 0, True, None])
def test_nonfinite_nonnumeric_and_bool_prices_fail(bad):
    d, rows = mk_fixture()
    rows[0]["open"] = bad
    with pytest.raises(ValueError):
        audit_cn_15m_against_daily(d, rows)


def test_invalid_ohlc_rejected():
    d, rows = mk_fixture()
    rows[0]["high"] = Decimal("1.18")
    with pytest.raises(ValueError, match="internally inconsistent"):
        audit_cn_15m_against_daily(d, rows)


def test_incomplete_empty_session_fail_closed():
    d, _ = mk_fixture()
    r = audit_cn_15m_against_daily(d, [])
    assert r.status == "INCOMPLETE"
    assert r.signal_confirmation_allowed is False
