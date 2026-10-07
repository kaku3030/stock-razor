from datetime import date, datetime, timedelta, timezone

from src.services.options_intelligence import (
    OptionGexObservation,
    build_gamma_profile,
    build_gex_evidence,
    build_options_intelligence_packet,
    qualify_options_clock_alignment,
    qualify_quote_freshness,
)
from src.services.options_intelligence.gamma_profile import apply_gamma_profile
from src.services.options_intelligence.gex import OptionType
from src.services.stock_radar_v2.options_context import (
    build_radar_options_context,
    normalize_options_underlying,
)


NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)


def _packet(
    *,
    underlying: str = "QQQ",
    generated_at: datetime = NOW,
    oi_known: bool = True,
):
    oi_asof = generated_at if oi_known else None
    rows = [
        OptionGexObservation(
            contract_symbol=f"{underlying}-C760",
            underlying_symbol=underlying,
            option_type=OptionType.CALL,
            strike=760,
            expiration=date(2026, 10, 16),
            open_interest=1200,
            gamma=0.02,
            contract_multiplier=100,
            source="futu_opend",
            quote_asof=generated_at,
            oi_asof=oi_asof,
            implied_volatility=0.25,
        ),
        OptionGexObservation(
            contract_symbol=f"{underlying}-P750",
            underlying_symbol=underlying,
            option_type=OptionType.PUT,
            strike=750,
            expiration=date(2026, 10, 16),
            open_interest=900,
            gamma=0.018,
            contract_multiplier=100,
            source="futu_opend",
            quote_asof=generated_at,
            oi_asof=oi_asof,
            implied_volatility=0.26,
        ),
    ]
    freshness = qualify_quote_freshness(
        rows,
        min_quote_asof=generated_at - timedelta(minutes=1),
    )
    clock = qualify_options_clock_alignment(
        freshness,
        underlying_asof=generated_at,
    )
    current = build_gex_evidence(
        rows,
        spot=755.0,
        market_date=generated_at.date(),
        calculated_at=generated_at,
        spot_asof=generated_at,
        spot_source="canonical_spot",
    )
    profile = build_gamma_profile(
        rows,
        reference_spot=755.0,
        calculated_at=generated_at,
    )
    current = apply_gamma_profile(current, profile)
    return build_options_intelligence_packet(
        current_gex=current,
        freshness=freshness,
        gamma_profile=profile,
        generated_at=generated_at,
        clock_alignment=clock,
    )


def test_normalize_options_underlying_handles_canonical_us_prefix():
    assert normalize_options_underlying("US.QQQ") == "QQQ"
    assert normalize_options_underlying("qqq") == "QQQ"


def test_context_is_read_only_when_packet_is_research_qualified():
    packet = _packet()
    context = build_radar_options_context(
        packet,
        expected_underlying="US.QQQ",
        observed_at=NOW + timedelta(seconds=5),
    )

    assert context.status == "RESEARCH_ONLY"
    assert context.options_regime in {
        "POSITIVE_GAMMA_ASSUMPTION",
        "NEGATIVE_GAMMA_ASSUMPTION",
        "NEUTRAL_OR_OFFSET",
    }
    assert context.price_acceptance_required is True
    assert context.decision_permission == "BLOCKED_V0_1"
    assert context.trading_authority is False
    assert context.live_trade is False


def test_context_preserves_degraded_unknown_oi_clock():
    packet = _packet(oi_known=False)
    context = build_radar_options_context(
        packet,
        expected_underlying="QQQ",
        observed_at=NOW,
    )

    assert packet.context_permission == "DEGRADED_RESEARCH"
    assert context.status == "DEGRADED_RESEARCH"
    assert context.clock_status == "DEGRADED"
    assert "oi_asof" in context.unknown_fields
    assert context.trading_authority is False


def test_stale_options_packet_is_blocked_without_changing_authority():
    old = NOW - timedelta(hours=1)
    packet = _packet(generated_at=old)
    context = build_radar_options_context(
        packet,
        expected_underlying="QQQ",
        observed_at=NOW,
    )

    assert context.status == "BLOCKED"
    assert "OPTIONS_PACKET_STALE" in context.warnings
    assert context.decision_permission == "BLOCKED_V0_1"
    assert context.trading_authority is False


def test_underlying_mismatch_is_blocked():
    packet = _packet(underlying="QQQ")
    context = build_radar_options_context(
        packet,
        expected_underlying="US.AMD",
        observed_at=NOW,
    )

    assert context.status == "BLOCKED"
    assert "OPTIONS_UNDERLYING_MISMATCH" in context.warnings
