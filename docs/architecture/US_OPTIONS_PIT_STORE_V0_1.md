# US Options PIT Store V0.1

Status: RESEARCH_ONLY / LIVE_TRADE=NO

## Purpose

Persist exactly what the options-intelligence layer observed at collection
time so historical research cannot silently substitute later Open Interest,
Greeks, IV, spot clocks, or normalization results for earlier market state.

## Contract

Each append-only snapshot records:

- underlying symbol
- collection timestamp
- spot, spot as-of, and spot source
- provider
- normalized option observations
- Open Interest
- Gamma and implied volatility
- option quote / Greeks as-of
- OI as-of when explicitly known; otherwise UNKNOWN remains UNKNOWN
- rejected source rows and their normalization reasons
- research_only=true
- live_trade=false

Snapshots are canonical-JSON serialized, SHA-256 addressed, gzip compressed,
and atomically written. An identical snapshot is idempotent. A changed field,
including changed OI, creates a different content digest and a new file.

## Live QQQ storage probe — 2026-10-07

Observed local OpenD chain:

- source rows: 2,110
- normalized usable rows: 2,110
- rejected rows: 0
- canonical JSON bytes: 642,812
- gzip bytes: 45,922 (~44.8 KiB)
- compressed/raw ratio: 0.0714

This demonstrates that full option-chain PIT retention is inexpensive enough
for frequent research snapshots. The measurement is a single QQQ snapshot and
is not a production capacity guarantee.

## Governance

PIT persistence proves what STOCK RAZOR captured, not that the provider data
was complete, current, entitled, or decision-grade. Freshness, three-clock
alignment, sign assumptions, provider lineage, and Radar admission remain
separate gates.
