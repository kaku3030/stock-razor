# US Options Intelligence / GEX V0.1

Status: RESEARCH_ONLY / CONTEXT_ONLY / LIVE_TRADE=NO

## Purpose

Provide options-positioning evidence to US Radar without creating an
independent trading authority.

The layer may describe:

- signed current-spot gamma exposure under an explicit sign convention
- net / absolute GEX
- strike-level GEX
- Call Wall / Put Wall
- 0DTE concentration
- a scenario Gamma Flip estimated by Black-Scholes gamma re-pricing
- data completeness, quote freshness, assumptions and UNKNOWN fields

It must not emit BUY / SELL / ENTER / EXIT authority.

## Intended flow

Option Chain
-> OI / IV / Greeks / timestamps
-> freshness qualification
-> current-spot GEX
-> static-IV gamma profile
-> Options Intelligence Packet
-> US Radar context
-> price acceptance / market structure
-> Main Control + Risk

## Primary candidate source

Current candidate: moomoo / Futu OpenD.

Observed local OpenD capability on 2026-10-07:

- US.QQQ option chain returned successfully.
- Seven-calendar-day chain contained 2,110 contracts.
- Market snapshot exposed:
  - option_open_interest
  - option_implied_volatility
  - option_delta
  - option_gamma
  - option_vega
  - option_theta
  - option_rho
  - option_contract_multiplier
  - option strike / expiry / type
  - quote update_time
- Contract multiplier observed for standard QQQ contracts: 100.
- A 120-contract near-ATM sample had OI, IV and Gamma populated for all 120 rows.

Official moomoo documentation states that U.S. option OI is updated during
the pre-market session. The observed snapshot does not expose a distinct
per-row OI timestamp, so STOCK RAZOR keeps oi_asof UNKNOWN instead of
reusing quote update_time.

## Alpaca cross-check role

Alpaca indicative option-chain access was successfully observed and can
provide quote/trade data plus IV and Greeks for many contracts.

The observed response did not provide Open Interest, so Alpaca alone is not
sufficient for the STOCK RAZOR GEX formula. It remains useful as an
independent quote / Greeks cross-check.

## Current-spot GEX formula

V0.1 uses:

GEX = Gamma * OpenInterest * ContractMultiplier * Spot^2 * 0.01

for a 1% underlying move.

Default sign convention:

- CALL: positive
- PUT: negative

This is a research positioning convention. It is not observed dealer
inventory. Every evidence packet therefore records:

- dealer_inventory_observed = false
- sign_convention = CALL_POSITIVE_PUT_NEGATIVE

No output may claim actual dealer positioning from OI alone.

## Futu normalization

The adapter converts Futu snapshot data into provider-neutral observations.

Important normalization rules:

- Futu option implied volatility is reported in percentage units and is
  converted to decimal form.
- U.S. option update_time is interpreted in America/New_York unless already
  timezone-aware.
- Missing or non-numeric OI / Gamma / strike / multiplier values are rejected.
- No missing values are invented.
- option_contract_multiplier is preferred, followed by contract size / lot
  size only as a compatibility fallback.

## Quote / Greek freshness gate

A live qualification probe showed that some far/illiquid QQQ option
snapshots retained quote/Greek update_time values from weeks earlier.

Therefore a full option chain must not be treated as current merely because
the chain request itself succeeded.

Pre-market research probe used:

- current QQQ spot: 759.66
- underlying update: 2026-10-07 06:45:59 ET
- expiration scope: 2026-10-07 through 2026-10-14
- total contracts: 2,110
- freshness floor: 2026-10-06 15:30 ET
- fresh contracts: 674
- freshness coverage: 31.94%
- qualification: DEGRADED

With that filtered set, the provisional research output was:

- Net GEX: approximately -355.1 million dollars per 1% move
- Call Wall: 762
- Put Wall: 755
- 0DTE absolute-GEX share: approximately 40.9%

These values are a pipeline validation result, not a trade recommendation.

The Call/Put walls remained stable compared with the unfiltered chain, but
coverage below 80% prevents PASS_RESEARCH.

## Gamma Flip V0.1

Gamma Flip is not derived from current Gamma values alone.

V0.1 re-prices Black-Scholes Gamma over a spot grid with frozen IV.

Default research assumptions:

- risk-free rate: 0.0
- dividend yield: 0.0
- expiration clock: 16:00 America/New_York
- spot grid: +/-12%
- grid points: 121
- IV: frozen at observed snapshot IV

Every profile carries STATIC_IV_REPRICING and
DEALER_POSITIONING_SIGN_IS_ASSUMED warnings.

Using the fresh QQQ subset above:

- repricable contracts: 668
- profile coverage versus source chain: 31.66%
- estimated static-IV Gamma Flip: approximately 760.64
- flip status: ESTIMATED_STATIC_IV

Because freshness/profile coverage is degraded and oi_asof is not explicitly
observed, this flip may only be used as contextual research evidence.

## Evidence permissions

OptionsIntelligencePacket V0.1 enforces:

- context_permission:
  - BLOCKED when no usable fresh evidence
  - DEGRADED_RESEARCH when coverage is below 80%
  - RESEARCH_ONLY when research gates pass
- radar_admission:
  - CONTEXT_ONLY when evidence is usable
  - BLOCKED otherwise
- decision_permission = BLOCKED_V0_1
- price_acceptance_required = true
- trading_authority = false
- live_trade = false

GEX therefore cannot independently create an order intent.

## UNKNOWN / degraded fields

Current known limitations:

- oi_asof: UNKNOWN at per-row level
- dealer inventory: NOT OBSERVED
- sign convention: ASSUMPTION
- static-IV gamma flip: MODEL ESTIMATE
- stale/illiquid contract Greeks can exist in a successful snapshot
- pre-market and regular-session freshness policies need separate thresholds
- risk-free rate and dividend yield require explicit production inputs
- historical PIT option-chain snapshots are not yet qualified

## Next gates

1. Implement session-aware freshness policy for pre-market and regular hours.
2. Define an auditable OI-as-of rule from provider semantics and collection
   evidence without pretending quote update_time is the OI timestamp.
3. Repeat live OpenD qualification after the U.S. options session opens.
4. Add independent Alpaca Greeks/quote cross-check on selected contracts.
5. Add historical snapshot persistence for PIT research.
6. Add profile sensitivity checks for rates, dividends, IV and grid width.
7. Add US Radar adapter that consumes OptionsIntelligencePacket as context
   only.
8. Keep LIVE_TRADE=NO until higher data, PIT, Shadow, Paper and execution gates
   pass.


## V0.1.1 session-aware / three-clock qualification

Live pre-market verification exposed a clock-consistency risk that is now
explicitly gated.

Three clocks are independent:

1. underlying spot as-of
2. option quote / Greeks as-of
3. Open Interest as-of

A successful option snapshot does not make those timestamps equivalent.

Observed example on 2026-10-07 pre-market:

- QQQ live/pre-market price had already updated on 2026-10-07.
- QQQ option quote/Greeks timestamps were mainly from the 2026-10-06
  regular-session close.
- Futu exposed OI values but did not expose a distinct per-contract OI
  timestamp in the observed snapshot.

Therefore STOCK RAZOR must not combine the current pre-market underlying
price with prior-close Greeks and label the result current GEX.

V0.1.1 adds:

- OptionsFreshnessPolicy
  - intraday / closing-auction floors are relative to the evaluation clock
  - pre-market / post-market / non-trading floors require an explicit
    completed exchange-session close
  - no weekday arithmetic is allowed to guess holidays
- OptionsClockQualification
  - blocks missing underlying as-of
  - blocks missing option quote as-of
  - blocks excessive spot-vs-option clock skew
  - keeps unknown OI as-of DEGRADED for research by default
  - may fail closed when require_oi_asof=true
- GexEvidence now carries spot_asof and spot_source.
- OptionsIntelligencePacket treats a BLOCKED clock qualification as BLOCKED
  context and still keeps decision_permission=BLOCKED_V0_1.

This preserves the rule:

same payload != same clock.

The Radar may consume GEX only as context after the clock/freshness layer
qualifies it; no GEX field independently changes trading authority.
