from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.services.options_intelligence.collector import (
    build_futu_options_intelligence_packet,
    resolve_us_options_session_context,
)


ET = ZoneInfo("America/New_York")


def _underlying(*, update_time: str, last: float = 760.0, prev_close: float = 756.2):
    return {
        "code": "US.QQQ",
        "last_price": last,
        "prev_close_price": prev_close,
        "update_time": update_time,
    }


def _option(
    *,
    code: str,
    option_type: str,
    strike: float,
    update_time: str,
    oi: int = 1000,
    gamma: float = 0.02,
    iv: float = 25.0,
    expiry: str = "2026-10-16",
):
    return {
        "code": code,
        "option_valid": True,
        "option_type": option_type,
        "option_strike_price": strike,
        "strike_time": expiry,
        "option_open_interest": oi,
        "option_gamma": gamma,
        "option_implied_volatility": iv,
        "option_contract_multiplier": 100.0,
        "update_time": update_time,
    }


def _pair(update_time: str):
    return [
        _option(
            code="US.QQQ261016C760000",
            option_type="CALL",
            strike=760,
            update_time=update_time,
            oi=1200,
            gamma=0.021,
        ),
        _option(
            code="US.QQQ261016P750000",
            option_type="PUT",
            strike=750,
            update_time=update_time,
            oi=900,
            gamma=0.019,
        ),
    ]


def test_session_context_uses_exchange_calendar_for_premarket_reference_close():
    now = datetime(2026, 10, 7, 7, 0, tzinfo=ET)
    context = resolve_us_options_session_context(now)

    assert context.status == "READY"
    assert context.phase == "premarket"
    assert context.reference_session_close is not None
    assert context.reference_session_close.date().isoformat() == "2026-10-06"
    assert context.reference_session_close.hour == 16


def test_session_context_respects_early_close_instead_of_assuming_1600():
    after_early_close = datetime(2026, 11, 27, 14, 0, tzinfo=ET)
    context = resolve_us_options_session_context(after_early_close)

    assert context.phase == "postmarket"
    assert context.session_close is not None
    assert context.session_close.hour == 13
    assert context.status == "BLOCKED_UNSUPPORTED_PHASE"


def test_premarket_packet_uses_previous_regular_close_and_stays_context_only():
    now = datetime(2026, 10, 7, 7, 0, tzinfo=ET)
    result = build_futu_options_intelligence_packet(
        symbol="US.QQQ",
        underlying_row=_underlying(
            update_time="2026-10-07 07:00:00",
            last=759.9,
            prev_close=756.2,
        ),
        option_rows=_pair("2026-10-06 15:50:00"),
        evaluated_at=now,
    )

    assert result.usable is True
    assert result.phase == "premarket"
    assert result.packet is not None
    assert result.packet.current_gex.spot == pytest.approx(756.2)
    assert result.packet.current_gex.spot_source == "previous_regular_close"
    assert result.packet.current_gex.spot_asof is not None
    assert result.packet.current_gex.spot_asof.hour == 16
    assert result.packet.radar_admission == "CONTEXT_ONLY"
    assert result.packet.decision_permission == "BLOCKED_V0_1"
    assert result.packet.context_permission == "DEGRADED_RESEARCH"
    assert result.clock is not None
    assert result.clock.status == "DEGRADED"
    assert "OI_ASOF_UNKNOWN" in result.clock.warnings


def test_intraday_packet_uses_aligned_live_underlying_clock():
    now = datetime(2026, 10, 7, 10, 0, tzinfo=ET)
    result = build_futu_options_intelligence_packet(
        symbol="QQQ",
        underlying_row=_underlying(
            update_time="2026-10-07 09:59:30",
            last=761.25,
            prev_close=756.2,
        ),
        option_rows=_pair("2026-10-07 09:58:00"),
        evaluated_at=now,
    )

    assert result.usable is True
    assert result.symbol == "US.QQQ"
    assert result.packet is not None
    assert result.packet.current_gex.spot == pytest.approx(761.25)
    assert result.packet.current_gex.spot_source == "regular_last"
    assert result.packet.current_gex.spot_asof is not None
    assert result.packet.current_gex.spot_asof.hour == 9
    assert result.clock is not None
    assert result.clock.status == "DEGRADED"
    assert result.packet.radar_admission == "CONTEXT_ONLY"


def test_intraday_stale_option_rows_fail_closed_before_gex_build():
    now = datetime(2026, 10, 7, 10, 0, tzinfo=ET)
    result = build_futu_options_intelligence_packet(
        symbol="QQQ",
        underlying_row=_underlying(update_time="2026-10-07 09:59:30"),
        option_rows=_pair("2026-10-06 16:00:00"),
        evaluated_at=now,
    )

    assert result.usable is False
    assert result.packet is None
    assert result.status == "BLOCKED"
    assert result.fresh_contracts == 0
    assert result.reasons == ("NO_FRESH_OPTION_OBSERVATIONS",)


def test_postmarket_collection_is_blocked_until_spot_semantics_are_qualified():
    now = datetime(2026, 10, 7, 17, 0, tzinfo=ET)
    result = build_futu_options_intelligence_packet(
        symbol="US.QQQ",
        underlying_row=_underlying(update_time="2026-10-07 16:00:00"),
        option_rows=_pair("2026-10-07 16:00:00"),
        evaluated_at=now,
    )

    assert result.usable is False
    assert result.packet is None
    assert result.phase == "postmarket"
    assert "POSTMARKET_SPOT_SEMANTICS_NOT_QUALIFIED" in result.reasons
