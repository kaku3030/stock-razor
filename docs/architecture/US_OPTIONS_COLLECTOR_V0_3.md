# US Options Intelligence Collector V0.3

Status: LOCAL_LAB / RESEARCH_ONLY / LIVE_TRADE=NO

## Purpose

Provide a separate, network-capable process that reads U.S. option-chain data
from local moomoo/Futu OpenD and publishes the atomic options-intelligence
sidecar introduced by GEX Runtime V0.2.

The collector is deliberately separate from the US Radar process.

Collector:
OpenD read-only quote context
-> option chain + snapshots
-> session-aware qualification
-> GEX / gamma profile
-> OptionsIntelligencePacket
-> atomic sidecar

Radar:
network-isolated worker
-> read-only sidecar
-> options_context only

## Provider boundary

The OpenD adapter:

- creates only OpenQuoteContext
- never creates a trading context
- uses get_market_snapshot and get_option_chain only
- normalizes symbols to US.*
- limits market-snapshot batches to 200 contracts
- defaults chain horizon to 7 calendar days
- closes the quote context after each active collection cycle

No order API is part of this layer.

## Session behavior

The collector uses exchange-calendars XNYS rather than weekday arithmetic.

Current V0.3 behavior:

- premarket:
  - collection allowed
  - spot = previous regular close
  - spot as-of = prior exchange session close
- intraday:
  - collection allowed
  - spot = current last price
  - spot as-of = underlying update_time
- postmarket:
  - blocked until Futu regular-vs-extended-hours spot semantics are qualified
- non-trading day:
  - blocked

A 2026-11-27 Black Friday test confirms the XNYS 13:00 ET early close is
recognized instead of assuming 16:00 ET.

## Atomic cycle behavior

A collection cycle:

1. resolves exchange phase before provider access
2. does not connect to OpenD in blocked phases
3. fetches each configured underlying independently
4. qualifies freshness and three-clock alignment
5. writes only qualified packets
6. may write a partial snapshot when some symbols fail
7. does not overwrite the prior sidecar when zero packets qualify

The final behavior allows the Radar reader's max-age gate to retire an old
sidecar instead of replacing it with fabricated fresh evidence.

## Initial scope / rate budget

Defaults:

- symbols: US.QQQ only
- poll interval: 60 seconds
- option horizon: 7 calendar days
- snapshot batch size: 200 contracts

Expansion to AMD / NVDA / TSLA is deferred until OpenD request rate, chain
size, latency and freshness are measured in cloud runtime.

## Local real-OpenD smoke

2026-10-07 premarket local smoke using the V0.3 adapter:

- underlying: QQQ
- option-chain contracts: 2,110
- option snapshot rows: 2,110
- normalized rows: 2,110
- freshness-qualified rows: 674
- freshness coverage: 31.94%
- phase: premarket
- collector status: DEGRADED_RESEARCH
- context permission: DEGRADED_RESEARCH
- Radar admission: CONTEXT_ONLY
- decision permission: BLOCKED_V0_1
- clock status: DEGRADED
- unresolved clock field: OI_ASOF_UNKNOWN
- Net GEX observed in that smoke: approximately -196.8M dollars per 1% move
- Call Wall: 762
- Put Wall: 755
- static-IV Gamma Flip: approximately 760.32

These values are transient validation evidence, not trade levels.

## AWS candidate service

The proposed installer creates a dedicated venv with:

- numpy 1.26.4
- pandas 2.2.2
- exchange-calendars 4.13.2
- futu-api 10.8.6808

Systemd candidate controls include:

- OPEND_HOST forced to 127.0.0.1
- NoNewPrivileges=true
- CapabilityBoundingSet empty
- ProtectSystem=strict
- ProtectHome=true
- IPAddressDeny=any
- IPAddressAllow=localhost
- restricted address families

Unlike the Radar worker, the collector cannot use PrivateNetwork=true because
it must reach the host OpenD loopback socket.

AWS_NETWORK_SANDBOX: UNVERIFIED

The localhost-only IPAddressAllow / IPAddressDeny behavior must be proven on
the actual AWS host before deployment admission.

## Admission state

- GEX Runtime V0.2 / PR #349: MERGED into canonical main
- exact-head local focused tests: PASS (110/110)
- real local OpenD read-only smoke: PASS
- live-trade authority: NO
- AWS verifier / deploy workflow: IMPLEMENTED, NOT_RUN
- AWS deployment: NOT_RUN
- AWS localhost-only sandbox: UNVERIFIED
- Radar sidecar enablement: BLOCKED until collector cloud qualification passes

## Next gates

1. Run required GitHub CI with this PR based directly on main.
2. Obtain Code Owner approval and merge only on an exact green HEAD.
3. Deploy the collector with US.QQQ only through the manual workflow.
4. Prove loopback OpenD access and non-loopback EPERM/EACCES under the
   configured systemd IP policy.
5. Verify cloud heartbeat and atomic sidecar provenance/currentness.
6. Measure one-minute cycle latency and provider request volume.
7. Repeat qualification during the regular option session after 09:30 ET.
8. Keep OI_ASOF UNKNOWN until a provider-semantic rule is independently
   justified.
9. Only then enable the Radar options-context slot.
