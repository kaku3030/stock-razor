# OpenD terminal minute and Paper repair acceptance

## OpenD terminal RTH minute

An OpenD stream can stop advancing regular-session end labels at 15:59 ET.
The accumulator then lacks the final 15:59–16:00 minute and its derived
5m/15m/1h terminal buckets remain incomplete despite a connected heartbeat.

After 16:30 America/New_York, the existing worker may request one same-provider
historical page per configured symbol, gated by that day's live label and
preceding-minute cache evidence. The page must contain all 390 sequential
regular-session minutes and have exhausted pagination. Only a missing final
minute is ingested. Existing unqualified terminal bars are rejected rather
than overwritten. Extended-session labels are not relabeled as regular.

There are at most two attempts per NY date, separated by at least 30 minutes;
successful or already-present results are not retried. A restart resets this
in-memory attempt state. Early-close sessions cannot satisfy the 390-minute
contract and remain unqualified by this repair.

The supplied minute retains `HISTORICAL_QUERY` provenance. It does not prove
realtime delivery, independent-source parity, or exchange finality. Acceptance
requires deployed source identity, post-close reconciliation evidence, and
canonical/MCP readback of the complete terminal grid with this provenance.

## Paper reservation isolation

Each cash reservation is reconstructed from its own durable reserve and BUY
fill receipts. Partial fills or release cannot free another intent's cash.
Unreserved BUY fills must fit unreserved buying power. BUY cash is reserved
before intent submission is journaled; insufficient cash therefore creates no
phantom submission. Returned simulated receipt batches are checked for reused
fill identities, side-specific limit prices, locked BUY notional, and owned
SELL quantity before accepted/fill journal transitions.

SQLite regressions cover partial fills, concurrent intents in one engine,
restart recovery, release, duplicate receipts, overspend and oversell. These
are offline simulations and do not validate broker-side simulated receipts,
cross-process transaction serialization, or production auto-execution.

## Paper schedule evidence

The read-only SSM probe accepts only all 48 unique local `HH:00`/`HH:30`
configuration slots and reports `CONFIGURED_48_SLOTS_ONLY`. One slot, missing
slots, duplicates, and off-grid values report `UNKNOWN`. Configuration does
not prove actual runs: runtime acceptance still requires distinct scheduled
trigger, start and completion records at both an hour and a half-hour.

## Deployment and rollback

Use existing protected-main workflows with immutable source SHA and their
existing restart/identity guards. Inspect the deployed service source and
cache provenance independently after deployment. Revert the integration
commit for a code rollback; use the existing controlled installer rollback
for a failed service update. Do not rewrite live journals or synthesize bars.

The MCP deployment workflow retains private installer output only within EC2
and publishes fixed failure diagnoses for Context Manager event schema,
sequence or integrity rejection, missing Python dependencies, or permissions.
The runner independently filters those enums. Unknown failures remain blocked;
diagnostics never repair or bypass an invalid event log.

`SOURCE_ARBITER_ADMISSION=BLOCKED`, `RADAR_ADMISSION=BLOCKED`,
`PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO`, `TRADE_EXECUTION=NO`.

## Context event sequence recovery

AWS run 38708985260 identified `CONTEXT_EVENT_SEQUENCE_INVALID` while
market caches remained readable. A two-process regression reproduced duplicate
version allocation. Writers now lock the entire read/allocate/append/publish
transaction using an OS lock shared across processes.

Ordinary deployments and reads never repair events. The owner-only, exact-main
MCP workflow has a transient manual input `repair_context_event_sequence`
(default false). The installer hashes the fixed AWS events file and passes
that digest to the explicit repair CLI. Under the writer lock, it requires
unchanged bytes, valid payload fingerprints, unique identities and only
consecutive duplicate/+1 versions. Gaps, regressions or other corruption block
recovery. It creates a byte-exact 0600 backup before replacing the log, retains
every event and its payload/provenance/timestamps/order, and only renumbers
versions before rebuilding state. All gates remain closed. Rebuild is safe to
retry if state publication failed after a successful log replacement.

Actual market evidence before this repair: Windows SDK 0.1.25 and AWS matched
144 historical rows / 864 OHLCVA values across two ETFs and four timeframes;
full-day 5m aggregation matched all 40 native 15m/60m groups. TickFlow deployed
SHA `6a2983b4d358617c433f1d90e665a4aa345cf4c7` in run 38707231457, and
OpenD in 38707388835. All nine OpenD symbols have the historical 15:59 ET
minute and complete terminal derived buckets. Paper isolated no-order restart
probe 38707695607 passed; permanent Paper service qualification still reports
UNKNOWN. After-close data does not prove active-session polling cadence,
independent source finality, or automatic Paper readiness.
