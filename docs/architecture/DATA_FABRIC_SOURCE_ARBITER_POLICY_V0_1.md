# US/CN Data Fabric Source Arbiter Policy V0.1 — SHADOW ONLY

Status: deterministic offline **source-selection proposal**, not operational
provider routing, canonical writer ownership or Data/Radar Admission.

## Objective

US Radar and CN Radar share the same decision rules and safety barriers but
may use different, qualified providers.

US eligible *names* are Desktop OpenD, Cloud OpenD, Alpaca/IEX, Twelve Data.
CN eligible *names* are Desktop/Cloud TickFlow, Desktop GM/QMT, Tencent, TDX,
Eastmoney, RQData. Inclusion in this enum **does not prove paid entitlement**
or source quality. TickFlow Expert paid access is not present and never
automatically upgraded.

Per `market/symbol/timeframe`, an upstream qualification service must
produce independent PASS/FAIL/UNKNOWN evidence for reachability, running
process, entitlement, freshness, sequence progression, continuity,
completeness and correctness. A tested, nonnegative finite latency, source
sequence and source age are also mandatory, with explicit staleness windows.
Source Arbiter discards any stale, missing or unqualified source, even when
it responds fastest.

Qualified candidates may compete; choose the fastest reported latency, with
a small configurable anti-flap threshold to avoid needless desktop/cloud
switching. If the incumbent is unqualified, propose a qualified cloud backup.
Unknown never becomes PASS, negative or future timestamps are not 0ms,
duplicate sources cannot propose two authoritative writers for a stream.

Output is `SHADOW_PROPOSAL`, not live routing. Even with a proposed provider:
`canonical_write_authorized=false`,
`single_writer_lease_acquired=false`,
`data_qualification=NOT_VERIFIED`,
`radar_admission=BLOCKED`, `can_confirm_signal=false`,
`live_trade=false`.

## Explicitly not implemented in this slice

1. Provider adapters, WebSocket manager, circuit breakers or retries.
2. Real cloud↔desktop reachability, entitlements, market data quality proof.
3. Atomic canonical writer/lease, fencing token and generation recovery.
4. Cross-source OHLCV and finality verification, market-session boundaries.
5. Runtime fallback, notifications, cloud service installation or orders.

An independent writer-leasing/fencing gate must be built and verified before
source arbitration may authoritatively publish market data. Provider
cross-check is separately reported, never inferred from a short latency.

## Planned runtime acceptance

- Desktop OpenD unplugged: Cloud OpenD remains warm, independently streaming
  and proposed; no gap in canonical sequence after fenced takeover.
- Desktop online: only fully qualified freshness/health/permission evidence
  can lead to a new proposal; avoid flapping on small latency jitter.
- Desktop/Cloud TickFlow requires proven concurrent-account/IP entitlement
  and original source event timestamps before being considered qualified.
- Both markets: P50/P95/P99 on unique source events, dropped/duplicate/
  out-of-order, data entitlement, source divergence, timeframes, CPU/RAM,
  reconnect, real cloud independence while local PC is actually off.
- Data Qualification and Radar Admission never implicitly follow from
  choosing a source; execution remains independently prohibited.
