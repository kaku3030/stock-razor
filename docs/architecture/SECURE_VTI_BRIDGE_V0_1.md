# Secure VTI Bridge V0.1

Status: RESEARCH_ONLY / LIVE_TRADE=NO

## Purpose

Expose canonical US bars to the browser without exposing provider credentials,
OpenD credentials, or STOCK_RAZOR_SNAPSHOT_READ_TOKEN.

## Security contract

- VTI browser route requires ADMIN_AUTH_ENABLED=true.
- A valid HttpOnly admin session cookie is mandatory.
- If admin auth is disabled, the VTI route returns 503 fail-closed.
- The browser never receives the internal snapshot-read bearer token.
- The VTI service performs no provider SDK calls and opens no subscriptions.
- The bridge reads only the existing canonical runtime snapshot.
- LIVE_TRADE remains NO.

## Data flow

OpenD -> canonical snapshot -> VtiMarketDataService
                              -> settled-bar cache (optional, downstream only)
                              -> /api/v1/data/vti/bars/{symbol}
                              -> KLineChart v10

## Cache policy

The settled-bar cache is opt-in:

- STOCK_RAZOR_SETTLED_BAR_CACHE_ENABLED=false
- STOCK_RAZOR_SETTLED_BAR_CACHE_PATH=data/cache/settled-bars.sqlite3

Only bars with is_closed=true AND is_complete=true are eligible for persistence.
A cache hit can eliminate repeated historical reads. A cache miss during left
pagination does not trigger provider I/O or an implicit historical backfill.

The cache does not establish:

- provider authority
- entitlement
- currentness
- timestamp semantics
- canonical status
- Radar admission
- trading permission

## KLineChart behavior

The browser uses the v10 data-loader model:

- getBars(init): recent server-side canonical/cache window
- getBars(forward): older settled-cache page using before=<bar timestamp>
- backward: disabled in V0.1
- subscribeBar: same-origin polling of the latest settled canonical bars
- unsubscribeBar: clears the polling handle

The VTI currently displays US canonical bars only. A-share intraday cache
admission remains blocked until timestamp/finality/currentness semantics are
qualified independently.

## Deployment gate

Before enabling the settled cache in cloud:

1. provision durable storage;
2. set an explicit cache path on that volume;
3. enable admin authentication;
4. verify filesystem ownership and backup/retention policy;
5. run read/write latency and restart-persistence checks;
6. keep cache failures non-authoritative and fail-open for chart reads only.
