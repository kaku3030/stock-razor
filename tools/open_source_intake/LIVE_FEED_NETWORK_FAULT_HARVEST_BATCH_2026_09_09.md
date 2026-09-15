# Open-Source Intake — LiveFeed Network / Provider Fault Harvest Batch 2026-09-09

Status: RESEARCH / DEFECT-AUDIT LEDGER. Non-production.

## Goal

Determine whether Radar needs a new external network-fault dependency now, or whether the existing LiveFeed/provider-semantics harness already covers the faults that matter in the current Foundation phase.

The decision rule is deliberately build-last:

> A mature fault-injection tool is not adopted merely because it can simulate more failures. It must close a proven Radar validation gap that cannot be covered safely and deterministically by existing assets.

## Existing Radar assets found during audit

### 1. Deterministic controller/adversarial coverage

Current/main or validated Draft assets already cover:

- bounded, nonblocking provider/event/control ingress;
- single-writer publication and deterministic cross-queue ordering;
- explicit ingress-loss evidence on queue overflow;
- STOP ordering and post-STOP reconnect suppression semantics;
- desired subscription registry revision/incarnation identity;
- provider-event runtime/provider/controller-generation relevance in Draft PR #30;
- generated lifecycle/stale-evidence sequences in Draft PR #32.

PR #30 exact head `bfaa193d91ce6dabd7c410691b9a9e5cedd501c5` has passed its own Research Radar Tests and repository CI.

PR #32 exact head `4d27c526dbb93c7430942c3e020ade4e5bf2ebcd` has passed its own Research Radar Tests and repository CI.

Neither is merged to main at this audit point; their status is `VALIDATING`, not mainline enforcement.

### 2. Existing localhost-only TCP fault proxy

Radar already contains `tools/provider_semantics/futu/transport_proxy.py`, a stdlib-only user-space TCP forwarder:

`Futu client -> 127.0.0.1:test_port -> proxy -> 127.0.0.1:OpenD`

It can:

- transparently forward the isolated experimental connection;
- `CUT`: sever the active client/upstream pair and immediately close newly accepted connections while cut;
- `RESTORE`: allow subsequent reconnects to reach OpenD again;
- `stop()`: hard, idempotent cleanup;
- record proxy lifecycle events with monotonic timestamps.

Its own local echo-server tests prove forwarding, active-pair cut, cut-time connection closure, restore, idempotent stop, exception cleanup, and local-port scope. These are harness-mechanics proofs only; they do not claim provider semantics.

This is important historical drift: the earlier `fault_injector.py` Level-1 note says safe transport interruption was not implemented. That statement describes the older harness state. The later Wave2 R1 `TransportProxy` closed that specific gap without firewall/routing changes.

### 3. Real Futu/OpenD transport-fault evidence

The Futu Semantic Contract records actual OpenD experiments, including:

- involuntary transport failure produced observable disconnect callbacks;
- SDK transport reconnect is autonomous;
- retry cadence was approximately six seconds in the tested version;
- no retry backoff/cap was observed in the tested source/behavior;
- three active-session cut/restore cycles independently reproduced reconnect behavior;
- after restore, tested QUOTE and K_1M pushes resumed without a manual `subscribe()` call;
- the tested K_1M recovery resumed at current/future progress rather than replaying the missed minute sequence;
- no authoritative replay/backfill marker was observed in the inspected QUOTE/K_1M payload surface;
- SDK-level reconnect/resubscribe is explicitly not controller recovery and not LIVE qualification.

These are provider evidence, not production-controller guarantees.

## External candidate: Shopify/toxiproxy

- URL: https://github.com/Shopify/toxiproxy
- Radar disposition now: `TEST-REUSE CANDIDATE / DEFER DIRECT DEPENDENCY`.

### What Toxiproxy would add beyond Radar's current proxy

Potentially useful later:

- configurable latency + jitter;
- upstream/downstream asymmetric faults;
- blackhole/timeout-style byte suppression;
- more reusable toxic composition;
- reset/connection-failure variants depending on exact version and toxic behavior.

### What it would NOT solve by itself

- provider SDK calls that block inside a production command worker;
- authentication/subscription/readiness qualification after transport recovery;
- currentness/continuity semantics;
- desired-vs-actual subscription reconciliation;
- stale runtime/provider/generation attribution;
- replay/backfill provenance when provider payloads do not expose an authoritative marker;
- LIVE qualification.

A proxy can create transport evidence. It cannot decide whether that evidence is sufficient for Radar trust.

### Toxiproxy audit cautions

Do not turn the external harness into a new oracle:

- fault-injection behavior itself must be characterized before relying on it;
- historical/current upstream issues show that some toxic lifecycle/probability behavior has had surprising edge cases;
- connect/accept timeout behavior is not equivalent to every real network failure mode;
- deterministic cleanup remains a Radar requirement, not an assumption inherited from the tool.

Therefore direct adoption now would increase CI/process/dependency surface before the current frozen capability owns the semantics those finer faults are meant to test.

## External candidate: nautechsystems/nautilus_trader

- URL: https://github.com/nautechsystems/nautilus_trader
- Radar disposition: `METHOD / TEST-REUSE`, no engine import.

High-value methods harvested:

1. transport availability and adapter readiness are separate facts;
2. `CONNECTED` means transport availability, not authentication/subscription replay/readiness;
3. reconnect should invalidate connection/authentication state first;
4. private sessions may require reauthentication before subscription replay;
5. subscription intent is retained independently of one send/ACK result;
6. local subscribe send success is not authoritative confirmation;
7. negative subscribe results should preserve recovery intent where appropriate;
8. unsubscribe correlation must not allow a stale unsubscribe acknowledgement to erase a later resubscribe;
9. shutdown must be bounded and repeated shutdown safe;
10. reconnect ownership/outcomes should distinguish already-reconnecting, disconnecting, closed, and unsupported states rather than collapsing everything into one boolean success.

These methods align strongly with Radar's existing frozen direction: `SDK reconnect/resubscribe != controller recovery != LIVE`.

## Fault coverage matrix

| Fault / failure mode | Existing Radar evidence | Current classification | Toxiproxy needed now? | Next owning capability |
|---|---|---|---|---|
| Active TCP connection severed | Existing `TransportProxy.cut()` + local harness test + real Futu Wave2 run | COVERED as harness/provider evidence | No | Provider semantics / recovery |
| Reconnect attempts blocked during outage | Existing proxy cut behavior + real Futu retry evidence | COVERED as harness/provider evidence | No | Provider semantics / recovery |
| Transport restored | Existing `restore()` + local harness test + real Futu cycles | COVERED as harness/provider evidence | No | Provider semantics / recovery |
| SDK autonomous reconnect | Real Futu evidence | PROVIDER-EVIDENCE | No | Adapter/recovery |
| SDK autonomous resubscribe | Real Futu 3-cycle evidence in tested scope | PROVIDER-EVIDENCE | No | Reconciliation / RecoveryCandidate |
| Old runtime/provider/generation callback | PR #30 focused repair + PR #32 generated sequences, both CI-green Drafts | VALIDATING-DRAFT | No | Identity/relevance |
| Shutdown followed by reconnect callback | Main Case 20 deterministic controller tests | ENFORCED+TESTED | No | Slice 1 closed area |
| Local ingress queue saturation | Main bounded queues + explicit `INGRESS_LOSS` evidence | STRUCTURALLY COVERED | No | Scheduling/backpressure refinement |
| Provider subscribe success but no push | Futu empirical evidence + LIVE structurally unreachable | PROVIDER-EVIDENCE / later semantic gap | No | Control/data-plane qualification |
| Provider subscription registry visible but no push ownership | Futu empirical evidence | PROVIDER-EVIDENCE | No | Reconciliation |
| Unsubscribe success with late callbacks | Futu empirical evidence | PROVIDER-EVIDENCE | No | stream-incarnation attribution |
| Synchronous provider RPC blocks during outage | Real historical Futu hang evidence; research `OutageRpcGuard` only | **PRODUCTION GAP / P0** | **No — proxy does not solve executor isolation** | Production LANE 3 executor |
| Provider context/connect call blocks | Real bounded-isolation evidence | **PRODUCTION GAP / P0** | No | Production LANE 3 executor |
| Fixed latency | Not modeled by current simple proxy | DEFERRED TEST GAP | Later, maybe | Currentness/Continuity |
| Latency jitter | Not modeled | DEFERRED TEST GAP | Later, likely useful | Currentness/Continuity |
| One-direction blackhole/asymmetry | Not modeled directly | DEFERRED TEST GAP | Later, useful | Currentness/Continuity + transport diagnostics |
| Bandwidth throttling / very slow stream | Not modeled | DEFERRED TEST GAP | Later, optional | Continuity/backpressure |
| Fine-grained reset variant | Current cut closes sockets; exact reset semantics not separately controlled | DEFERRED TEST GAP | Later, optional | Adapter transport tests |
| Half-open / byte blackhole without immediate close | Not modeled by current proxy | DEFERRED TEST GAP | Later, useful | timeouts/currentness |
| Slow TCP accept / connect-timeout variants | Not faithfully covered by current proxy and not assumed solved by Toxiproxy | OPEN SPECIALIZED GAP | Only with a proven test design | Production connection boundary |
| Current-looking event then silence | Frozen Case 35 deferred | SEMANTIC GAP | Proxy may help generate evidence later | Currentness + Continuity |
| Transport heartbeat but no market progress | Frozen Case 39 deferred | SEMANTIC GAP | Proxy alone insufficient | Continuity |
| Recovery currentness vs catch-up/backfill | Futu provider evidence exists; controller classification deferred | SEMANTIC GAP | No | CurrentnessBoundary + RecoveryCandidate |
| Cache trust after disconnect | Frozen Case 11 deferred | SEMANTIC GAP | No | Cache trust / final health |

## Key defect-audit conclusion

The current high-priority reliability gap is **not insufficient network-fault variety**.

It is the unresolved production LANE 3 blocking boundary.

`src/services/live_feed/commands.py` explicitly defines `ProviderCommandExecutor.submit()` as a nonblocking boundary, but the only implementation in the current Slice-1 source is `FakeProviderCommandExecutor`, which is synchronous and test-only. The Blocking Execution Model explicitly leaves thread-timeout vs process isolation unresolved, while the project's own Futu research has already demonstrated that provider construction and synchronous RPC calls can block for operationally unacceptable durations.

Therefore:

> Adding latency/jitter toxics before defining a production-safe provider command executor would test a more detailed network world around an execution boundary that still cannot guarantee bounded failure.

That is the wrong dependency order.

## Decision

### Toxiproxy

`DEFER DIRECT DEPENDENCY`.

Do not add it to production or CI requirements now.

Re-open the candidate when **Currentness / Continuity / RecoveryCandidate or real adapter Shadow validation** enters implementation and at least one of these becomes an acceptance criterion:

- deterministic latency/jitter thresholds;
- one-direction blackhole;
- prolonged byte-level stall without immediate socket close;
- bandwidth degradation;
- reproducible intermittent/flapping network conditions not expressible cleanly through the current local proxy.

At that point, first characterize the exact Toxiproxy version/toxic behavior in a local echo-server self-test before using it against OpenD or treating it as evidence.

### NautilusTrader

`HARVEST METHODS NOW; NO ENGINE IMPORT`.

Carry the following into Radar Slice 2 design/review:

`transport_restored -> auth_invalidated/revalidated -> desired intent replay/reconciliation -> data-plane currentness -> continuity -> recovery qualification -> LIVE`

Do not collapse any adjacent arrow into one provider return code or socket event.

## Next implementation priority produced by this audit

1. Freeze the production LANE 3 executor requirements before coding an adapter.
2. Decide the cancellation boundary: process isolation vs another mechanism that can actually bound a stuck provider call.
3. Define timeout result identity and stale-result handling against controller generation + desired revision + stream incarnation.
4. Only after that boundary is credible, proceed to provider adapter/reconciliation and Currentness/Continuity.
5. Add Toxiproxy-style fine-grained network faults when those later capabilities have explicit assertions to test.

## Governing rule

> Fault injection is valuable only when Radar already knows what invariant the fault is supposed to prove.

More fault knobs are not more reliability by themselves.
