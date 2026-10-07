# US Options GEX Runtime V0.2

Status: RESEARCH_ONLY / CONTEXT_ONLY / LIVE_TRADE=NO

## Goal

Move the qualified GEX evidence from an in-process research object into a
safe sidecar that the isolated US Radar worker can consume without opening a
provider connection.

The V0.2 boundary is:

Options Collector (future)
-> OptionsIntelligencePacket
-> atomic options-intelligence snapshot
-> fail-closed RadarOptionsContextReader
-> per-symbol options_context
-> US Radar research heartbeat

The Radar worker remains unable to fetch option data itself.

## Safety boundary

The runtime snapshot requires:

- exact repo SHA
- runtime instance id
- positive sequence
- timezone-aware emitted_at
- research_only=true
- trading_authority=false
- live_trade=false
- packet decision_permission=BLOCKED_V0_1

The reader additionally requires:

- exact schema
- canonical US symbol keys
- packet underlying-symbol match
- price_acceptance_required=true
- clock_alignment present
- decision_permission still blocked
- context/radar permissions consistent
- finite numeric GEX values
- bounded completeness / 0DTE share
- exact source SHA when configured
- snapshot not stale
- snapshot not materially from the future

Any contract failure becomes BLOCKED with no context emitted.

## Radar integration

Canonical technical state and Options Intelligence remain separate.

CanonicalRadarSymbolResult now has an optional options_context field.

Adding or changing options_context:

- does not change technical_state
- does not change signal_permission
- does not change can_confirm_signal
- does not change radar_admission
- does not authorize any order intent

If the canonical sequence is unchanged but the options snapshot changes, the
worker may refresh options_context while retaining the already-computed
technical state.

## AWS worker slot

The existing US Radar worker remains:

- PrivateNetwork=true
- NoNewPrivileges=true
- provider-SDK free
- Futu/Alpaca free
- read-only against acquisition runtime paths

Options context is opt-in:

- OPTIONS_CONTEXT_ENABLED defaults to false
- enabling requires an exact OPTIONS_SOURCE_REPO_SHA
- sidecar path defaults to
  /run/stock-razor-us-options-intelligence/options-intelligence.json
- Radar receives only a read-only path
- missing/invalid/stale sidecar produces no options context

This PR does not deploy an Options Collector. It only prepares the safe
runtime contract and read-only consumer.

## Live qualification evidence before V0.2

Local moomoo OpenD QQQ pre-market qualification on 2026-10-07:

- option-chain rows: 2,110
- normalized: 2,110
- freshness-qualified rows: 674
- freshness coverage: 31.94%
- freshness: DEGRADED
- three-clock gate: DEGRADED
- unresolved field: OI_ASOF_UNKNOWN
- radar admission: CONTEXT_ONLY
- decision permission: BLOCKED_V0_1

One observed qualified research snapshot, using prior regular close as the
aligned spot clock, produced approximately:

- Net GEX: -196.8 million dollars per 1% move
- Call Wall: 762
- Put Wall: 755
- 0DTE absolute-GEX share: 41.5%
- static-IV Gamma Flip: 760.42

These numbers are validation evidence only. They are not persistent market
levels and are not a trade recommendation.

## Next gates

1. Build a separate network-capable Options Collector around local/cloud
   OpenD.
2. Export V0.2 snapshots atomically with exact collector repo SHA.
3. Deploy collector separately from the network-isolated Radar worker.
4. Verify live-session options quote/Greeks coverage after 09:30 ET.
5. Establish an auditable provider rule for OI as-of.
6. Add historical PIT option-chain snapshot persistence.
7. Only after the above, enable OPTIONS_CONTEXT_ENABLED in the Radar runtime.
8. Keep LIVE_TRADE=NO.
