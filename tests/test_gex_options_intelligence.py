from datetime import date, datetime, timedelta, timezone

import pytest

from src.services.options_intelligence.futu_snapshot_adapter import (
    normalize_futu_snapshot_rows,
)
from src.services.options_intelligence.gex import (
    GexAssumptionSet,
    OptionGexObservation,
    OptionType,
    build_gex_evidence,
)


NOW = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
MARKET_DATE = date(2026, 10, 7)


def _obs(
    *,
    symbol: str,
    option_type: OptionType,
    strike: float,
    oi: int,
    gamma: float,
    expiration: date = MARKET_DATE,
    quote_asof: datetime | None = NOW,
    oi_asof: datetime | None = None,
) -> OptionGexObservation:
    return OptionGexObservation(
        contract_symbol=symbol,
        underlying_symbol="QQQ",
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        open_interest=oi,
        gamma=gamma,
        contract_multiplier=100,
        source="futu_opend",
        quote_asof=quote_asof,
        oi_asof=oi_asof,
        implied_volatility=0.25,
    )


def test_gex_formula_and_sign_assumption_are_explicit():
    evidence = build_gex_evidence(
        [
            _obs(
                symbol="QQQ-C100",
                option_type=OptionType.CALL,
                strike=100,
                oi=100,
                gamma=0.01,
            ),
            _obs(
                symbol="QQQ-P100",
                option_type=OptionType.PUT,
                strike=100,
                oi=50,
                gamma=0.02,
            ),
        ],
        spot=100,
        market_date=MARKET_DATE,
        calculated_at=NOW,
    )

    assert evidence.call_gex == pytest.approx(10_000)
    assert evidence.put_gex == pytest.approx(-10_000)
    assert evidence.net_gex == pytest.approx(0)
    assert evidence.absolute_gex == pytest.approx(20_000)
    assert evidence.assumption_set.dealer_inventory_observed is False
    assert (
        "SIGNED_GEX_USES_POSITIONING_ASSUMPTION_NOT_OBSERVED_DEALER_INVENTORY"
        in evidence.warnings
    )


def test_walls_and_zero_dte_concentration_use_absolute_exposure():
    evidence = build_gex_evidence(
        [
            _obs(
                symbol="QQQ-C100",
                option_type=OptionType.CALL,
                strike=100,
                oi=100,
                gamma=0.01,
            ),
            _obs(
                symbol="QQQ-C105",
                option_type=OptionType.CALL,
                strike=105,
                oi=300,
                gamma=0.01,
                expiration=date(2026, 10, 8),
            ),
            _obs(
                symbol="QQQ-P95",
                option_type=OptionType.PUT,
                strike=95,
                oi=400,
                gamma=0.02,
            ),
        ],
        spot=100,
        market_date=MARKET_DATE,
        calculated_at=NOW,
    )

    assert evidence.call_wall == 105
    assert evidence.put_wall == 95
    assert evidence.zero_dte_share == pytest.approx(90_000 / 120_000)
    assert evidence.strongest_positive_strike == 105
    assert evidence.strongest_negative_strike == 95


def test_gamma_flip_and_oi_asof_remain_unknown_when_not_observed():
    evidence = build_gex_evidence(
        [
            _obs(
                symbol="QQQ-C100",
                option_type=OptionType.CALL,
                strike=100,
                oi=100,
                gamma=0.01,
            )
        ],
        spot=100,
        market_date=MARKET_DATE,
        calculated_at=NOW,
    )

    payload = evidence.to_payload()

    assert evidence.gamma_flip is None
    assert evidence.gamma_flip_status == "UNKNOWN_REPRICING_NOT_IMPLEMENTED"
    assert "gamma_flip" in evidence.unknown_fields
    assert "oi_asof" in evidence.unknown_fields
    assert payload["trading_authority"] is False
    assert payload["research_only"] is True


def test_source_contract_total_preserves_rejected_row_coverage():
    evidence = build_gex_evidence(
        [
            _obs(
                symbol="QQQ-C100",
                option_type=OptionType.CALL,
                strike=100,
                oi=100,
                gamma=0.01,
            )
        ],
        spot=100,
        market_date=MARKET_DATE,
        calculated_at=NOW,
        source_contracts_total=4,
    )

    assert evidence.contracts_total == 4
    assert evidence.contracts_usable == 1
    assert evidence.completeness == pytest.approx(0.25)


def test_futu_adapter_normalizes_percent_iv_and_market_time():
    result = normalize_futu_snapshot_rows(
        [
            {
                "code": "US.QQQ261007P750000",
                "option_valid": True,
                "option_type": "PUT",
                "option_strike_price": 750.0,
                "strike_time": "2026-10-07",
                "option_open_interest": 15323,
                "option_gamma": 0.018793,
                "option_implied_volatility": 25.809,
                "option_contract_multiplier": 100.0,
                "option_contract_size": 100.0,
                "lot_size": 100,
                "update_time": "2026-10-06 16:14:54",
            }
        ],
        underlying_symbol="QQQ",
    )

    assert result.usable_rows == 1
    assert result.completeness == 1.0
    row = result.observations[0]
    assert row.implied_volatility == pytest.approx(0.25809)
    assert row.quote_asof is not None
    assert row.quote_asof.tzinfo is not None
    assert row.quote_asof.utcoffset() is not None
    assert row.contract_multiplier == 100.0
    assert row.open_interest == 15323


def test_futu_adapter_rejects_incomplete_rows_without_inventing_values():
    result = normalize_futu_snapshot_rows(
        [
            {
                "code": "US.QQQ261007P750000",
                "option_valid": True,
                "option_type": "PUT",
                "option_strike_price": 750.0,
                "strike_time": "2026-10-07",
                "option_open_interest": 15323,
                "option_gamma": "N/A",
                "option_contract_multiplier": 100.0,
                "update_time": "2026-10-06 16:14:54",
            },
            {
                "code": "US.QQQ261007C750000",
                "option_valid": True,
                "option_type": "CALL",
                "option_strike_price": 750.0,
                "strike_time": "2026-10-07",
                "option_open_interest": 100,
                "option_gamma": 0.02,
                "option_contract_multiplier": 100.0,
                "update_time": "2026-10-06 16:14:54",
            },
        ],
        underlying_symbol="QQQ",
    )

    assert result.total_rows == 2
    assert result.usable_rows == 1
    assert result.completeness == pytest.approx(0.5)
    assert len(result.rejected) == 1
    assert "option_gamma" in result.rejected[0].reason


def test_rejects_claim_that_dealer_inventory_is_observed():
    with pytest.raises(ValueError):
        GexAssumptionSet(dealer_inventory_observed=True)


from src.services.options_intelligence.gamma_profile import (
    GammaRepricingAssumptions,
    apply_gamma_profile,
    black_scholes_gamma,
    build_gamma_profile,
)
from src.services.options_intelligence.qualification import (
    qualify_options_clock_alignment,
    qualify_quote_freshness,
    qualify_quote_freshness_with_policy,
    resolve_us_options_freshness_policy,
)


def test_quote_freshness_gate_preserves_coverage_and_degrades_low_coverage():
    old = datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)
    fresh = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    cutoff = datetime(2026, 10, 6, 19, 30, tzinfo=timezone.utc)

    rows = [
        _obs(
            symbol="QQQ-C100",
            option_type=OptionType.CALL,
            strike=100,
            oi=100,
            gamma=0.01,
            quote_asof=fresh,
        ),
        _obs(
            symbol="QQQ-P100",
            option_type=OptionType.PUT,
            strike=100,
            oi=100,
            gamma=0.01,
            quote_asof=old,
        ),
        _obs(
            symbol="QQQ-C105",
            option_type=OptionType.CALL,
            strike=105,
            oi=100,
            gamma=0.01,
            quote_asof=None,
        ),
    ]

    result = qualify_quote_freshness(rows, min_quote_asof=cutoff)

    assert result.usable == 1
    assert result.source_total == 3
    assert result.stale_rejected == 1
    assert result.missing_timestamp_rejected == 1
    assert result.completeness == pytest.approx(1 / 3)
    assert result.status == "DEGRADED"


def test_black_scholes_gamma_is_positive_for_valid_contract():
    value = black_scholes_gamma(
        spot=100,
        strike=100,
        volatility=0.25,
        time_years=30 / 365,
        risk_free_rate=0.0,
        dividend_yield=0.0,
    )

    assert value > 0


def test_gamma_profile_estimates_flip_with_static_iv_and_keeps_warning():
    expiry = date(2026, 10, 17)
    rows = [
        OptionGexObservation(
            contract_symbol="QQQ-C105",
            underlying_symbol="QQQ",
            option_type=OptionType.CALL,
            strike=105,
            expiration=expiry,
            open_interest=100,
            gamma=0.01,
            contract_multiplier=100,
            source="futu_opend",
            quote_asof=NOW,
            implied_volatility=0.25,
        ),
        OptionGexObservation(
            contract_symbol="QQQ-P95",
            underlying_symbol="QQQ",
            option_type=OptionType.PUT,
            strike=95,
            expiration=expiry,
            open_interest=100,
            gamma=0.01,
            contract_multiplier=100,
            source="futu_opend",
            quote_asof=NOW,
            implied_volatility=0.25,
        ),
    ]

    profile = build_gamma_profile(
        rows,
        reference_spot=100,
        calculated_at=NOW,
        repricing=GammaRepricingAssumptions(
            spot_range_fraction=0.15,
            grid_points=121,
        ),
    )

    assert profile.flip_status == "ESTIMATED_STATIC_IV"
    assert profile.gamma_flip is not None
    assert 98 < profile.gamma_flip < 102
    assert "STATIC_IV_REPRICING" in profile.warnings

    evidence = build_gex_evidence(
        rows,
        spot=100,
        market_date=MARKET_DATE,
        calculated_at=NOW,
    )
    enriched = apply_gamma_profile(evidence, profile)

    assert enriched.gamma_flip == pytest.approx(profile.gamma_flip)
    assert "gamma_flip" not in enriched.unknown_fields
    assert enriched.trading_authority is False


def test_gamma_profile_refuses_to_fake_flip_without_reprice_inputs():
    row = _obs(
        symbol="QQQ-C100",
        option_type=OptionType.CALL,
        strike=100,
        oi=100,
        gamma=0.01,
    )
    row = OptionGexObservation(
        contract_symbol=row.contract_symbol,
        underlying_symbol=row.underlying_symbol,
        option_type=row.option_type,
        strike=row.strike,
        expiration=date(2026, 10, 17),
        open_interest=row.open_interest,
        gamma=row.gamma,
        contract_multiplier=row.contract_multiplier,
        source=row.source,
        quote_asof=row.quote_asof,
        oi_asof=row.oi_asof,
        implied_volatility=None,
    )

    profile = build_gamma_profile(
        [row],
        reference_spot=100,
        calculated_at=NOW,
    )

    assert profile.gamma_flip is None
    assert profile.flip_status == "UNKNOWN_NO_REPRICABLE_CONTRACTS"
    assert profile.contracts_usable == 0


from src.services.options_intelligence.contract import (
    build_options_intelligence_packet,
)


def test_options_packet_is_context_only_and_never_trading_authority():
    rows = [
        _obs(
            symbol="QQQ-C100",
            option_type=OptionType.CALL,
            strike=100,
            oi=100,
            gamma=0.01,
            quote_asof=NOW,
        )
    ]
    freshness = qualify_quote_freshness(
        rows,
        min_quote_asof=datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc),
    )
    current = build_gex_evidence(
        rows,
        spot=100,
        market_date=MARKET_DATE,
        calculated_at=NOW,
        source_contracts_total=freshness.source_total,
    )
    profile = build_gamma_profile(
        rows,
        reference_spot=100,
        calculated_at=NOW,
        source_contracts_total=freshness.source_total,
    )

    packet = build_options_intelligence_packet(
        current_gex=current,
        freshness=freshness,
        gamma_profile=profile,
        generated_at=NOW,
    )
    payload = packet.to_payload()

    assert packet.radar_admission == "CONTEXT_ONLY"
    assert packet.decision_permission == "BLOCKED_V0_1"
    assert payload["price_acceptance_required"] is True
    assert payload["trading_authority"] is False
    assert payload["live_trade"] is False


def test_premarket_policy_requires_explicit_completed_session_reference():
    evaluated_at = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)

    blocked = resolve_us_options_freshness_policy(
        evaluated_at=evaluated_at,
        phase="premarket",
    )
    assert blocked.status == "BLOCKED_UNKNOWN_SESSION_REFERENCE"
    assert blocked.min_quote_asof is None

    prior_close = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    ready = resolve_us_options_freshness_policy(
        evaluated_at=evaluated_at,
        phase="premarket",
        reference_session_close=prior_close,
    )
    assert ready.status == "READY"
    assert ready.min_quote_asof == prior_close - timedelta(minutes=30)

    rows = [
        _obs(
            symbol="QQQ-C100",
            option_type=OptionType.CALL,
            strike=100,
            oi=100,
            gamma=0.01,
            quote_asof=datetime(2026, 10, 6, 19, 45, tzinfo=timezone.utc),
        )
    ]
    qualified = qualify_quote_freshness_with_policy(rows, policy=ready)
    assert qualified.status == "PASS_RESEARCH"
    assert qualified.policy_phase == "premarket"


def test_clock_gate_blocks_live_premarket_spot_mixed_with_prior_close_greeks():
    rows = [
        _obs(
            symbol="QQQ-C100",
            option_type=OptionType.CALL,
            strike=100,
            oi=100,
            gamma=0.01,
            quote_asof=datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc),
        )
    ]
    freshness = qualify_quote_freshness(
        rows,
        min_quote_asof=datetime(2026, 10, 6, 19, 30, tzinfo=timezone.utc),
    )

    clock = qualify_options_clock_alignment(
        freshness,
        underlying_asof=datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc),
    )

    assert clock.status == "BLOCKED"
    assert "UNDERLYING_OPTION_CLOCK_SKEW_TOO_LARGE" in clock.warnings


def test_clock_gate_allows_aligned_spot_but_degrades_unknown_oi_clock():
    rows = [
        _obs(
            symbol="QQQ-C100",
            option_type=OptionType.CALL,
            strike=100,
            oi=100,
            gamma=0.01,
            quote_asof=datetime(2026, 10, 6, 20, 10, tzinfo=timezone.utc),
            oi_asof=None,
        )
    ]
    freshness = qualify_quote_freshness(
        rows,
        min_quote_asof=datetime(2026, 10, 6, 19, 30, tzinfo=timezone.utc),
    )
    clock = qualify_options_clock_alignment(
        freshness,
        underlying_asof=datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc),
    )

    assert clock.status == "DEGRADED"
    assert clock.actual_underlying_quote_skew_seconds == pytest.approx(600)
    assert "OI_ASOF_UNKNOWN" in clock.warnings


def test_packet_blocks_context_when_three_clock_gate_is_blocked():
    rows = [
        _obs(
            symbol="QQQ-C100",
            option_type=OptionType.CALL,
            strike=100,
            oi=100,
            gamma=0.01,
            expiration=date(2026, 10, 17),
            quote_asof=datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc),
        )
    ]
    freshness = qualify_quote_freshness(
        rows,
        min_quote_asof=datetime(2026, 10, 6, 19, 30, tzinfo=timezone.utc),
    )
    current = build_gex_evidence(
        rows,
        spot=100,
        market_date=MARKET_DATE,
        calculated_at=NOW,
        spot_asof=datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc),
        spot_source="premarket_last",
    )
    profile = build_gamma_profile(
        rows,
        reference_spot=100,
        calculated_at=NOW,
    )
    clock = qualify_options_clock_alignment(
        freshness,
        underlying_asof=current.spot_asof,
    )
    packet = build_options_intelligence_packet(
        current_gex=current,
        freshness=freshness,
        gamma_profile=profile,
        generated_at=NOW,
        clock_alignment=clock,
    )

    assert packet.context_permission == "BLOCKED"
    assert packet.radar_admission == "BLOCKED"
    assert packet.decision_permission == "BLOCKED_V0_1"


def test_gex_payload_declares_spot_clock_and_source():
    rows = [
        _obs(
            symbol="QQQ-C100",
            option_type=OptionType.CALL,
            strike=100,
            oi=100,
            gamma=0.01,
        )
    ]
    spot_asof = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    evidence = build_gex_evidence(
        rows,
        spot=100,
        market_date=MARKET_DATE,
        calculated_at=NOW,
        spot_asof=spot_asof,
        spot_source="official_close",
    )

    payload = evidence.to_payload()
    assert payload["spot_asof"] == spot_asof.isoformat()
    assert payload["spot_source"] == "official_close"
    assert "spot_asof" not in evidence.unknown_fields
    assert "spot_source" not in evidence.unknown_fields
