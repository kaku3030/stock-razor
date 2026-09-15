# LiveFeed Provider Worker Supervisor — Design Freeze V0.1

Status: **DESIGN: FROZEN**
Implementation: **NOT STARTED**
Production/Shadow promotion: **NOT GRANTED**

Frozen on: 2026-09-09

## 1. Authority

This freeze composes, and is subordinate to, the authoritative provider-neutral Live Feed Reliability V0.1 frozen contract.

The frozen execution design is the combined result of:

1. `LIVE_FEED_BLOCKING_EXECUTOR_HARVEST_BATCH_2026_09_09.md`
2. `LIVE_FEED_PROVIDER_WORKER_CONTRACT_CANDIDATE_V0_1.md`
3. `LIVE_FEED_BLOCKING_EXECUTOR_ADVERSARIAL_REVIEW_2026_09_09.md`
4. `LIVE_FEED_PROVIDER_WORKER_INTEGRATION_REVIEW_R2_2026_09_09.md`
5. `LIVE_FEED_PROVIDER_WORKER_CONTRACT_SHAPE_R3_2026_09_09.md`
6. `LIVE_FEED_PROVIDER_WORKER_FINAL_ADVERSARIAL_REVIEW_R4_2026_09_09.md`

Where an earlier candidate wording conflicts with a later review resolution, the later review wins. This freeze records the resulting design, not the chronological debate.

## 2. Frozen architecture

```text
LiveFeed authoritative writer
        ^
        | globally sequenced execution/provider/control evidence
        |
ProviderWorkerSupervisor  (parent process, one coordinator state writer)
        |
        | generation-local command IPC
        v
ProviderWorkerProcess generation N
        |
        +-- owns provider SDK/context
        +-- owns synchronous provider RPC execution
        +-- owns SDK callback handlers
        |
        | one child IPC sender, strict PRIORITY before DATA
        v
parent watcher -> bounded supervisor evidence ingress
```

One provider session/context belongs to one isolated provider worker process generation.

## 3. Frozen negative constraints

The implementation MUST NOT:

- call potentially blocking provider SDK methods on the LiveFeed authoritative writer;
- claim a caller wait timeout is a hard timeout while the provider call keeps running;
- use a normal Python thread as the sole kill boundary for a stuck provider SDK call;
- let supervisor/watcher/callback threads mutate LiveFeed authoritative truth;
- let worker restart imply transport recovery, Currentness, Continuity, or LIVE;
- conflate worker generation with controller/connection generation, desired revision, or stream subscription epoch;
- replay queued/in-flight provider commands automatically across worker-generation replacement;
- reuse IPC endpoints after worker death/kill;
- use arbitrary pickle/provider objects as the provider-worker wire protocol;
- silently drop terminal/lifecycle/protocol priority evidence;
- rebind one worker generation in place to a newer controller-generation callback identity;
- infer provider success/rejection after worker crash or timeout;
- spawn a replacement worker when an old worker cannot be proven dead;
- add a permissive fallback timeout for unknown/future command types;
- allow market-data DATA backlog to starve command/lifecycle PRIORITY evidence.

## 4. Frozen execution identities

These identities remain orthogonal:

1. `runtime_instance_id`
2. controller/connection generation identity owned by LiveFeed recovery integration
3. `worker_generation` owned only by provider execution supervisor
4. `desired_registry_revision`
5. `stream_subscription_epoch`
6. `SemanticStreamKey`

Provider-native `conn_id`, socket identifiers, PID, callback thread id, or Python object identity are diagnostic only unless separately proven otherwise.

A worker generation has one immutable `controller_generation_binding` for provider callbacks in V0.1. Controller-generation change may require a fresh worker generation; worker-generation change never automatically changes controller generation.

## 5. Frozen supervisor model

Supervisor states:

- `ABSENT`
- `STARTING`
- `IDLE`
- `BUSY`
- `STOPPING`
- `DEAD`
- `FATAL`

Only one parent `SupervisorCoordinator` mutates supervisor lifecycle, in-flight command, terminal outcome, cancellation, current worker generation, and fatality state.

Other threads/process paths are intent/evidence producers only.

One synchronous provider RPC may be RUNNING per worker generation.

## 6. Frozen hard-timeout rule

A timeout is valid only when the stuck execution capability is invalidated and the worker process is terminated/killed under a bounded parent-owned death-confirmation sequence.

If death cannot be confirmed:

- supervisor enters `FATAL`;
- replacement spawn is forbidden;
- intervention-required execution failure is surfaced.

All elapsed deadlines use parent monotonic time.

Complete parent frame observation time is deadline authority:

```text
observed_ns < deadline_ns  -> result may be timely
observed_ns >= deadline_ns -> TIMEOUT wins
```

Child-reported completion timestamps cannot override this boundary.

## 7. Frozen terminal outcome vocabulary

- `SUCCEEDED`
- `PROVIDER_REJECTED`
- `PROVIDER_EXCEPTION`
- `TIMEOUT`
- `WORKER_EXITED`
- `PROTOCOL_ERROR`
- `CANCELLED_SHUTDOWN`
- `CANCELLED_GENERATION_INVALIDATED`

Exactly one terminal outcome may win per command id.

`ProviderCommandResult.succeeded: bool` is not the infrastructure terminal vocabulary.

## 8. Frozen worker evidence vocabulary

- `WORKER_RUNTIME_STARTED`
- `WORKER_RUNTIME_READY`
- `WORKER_INIT_FAILED`
- `WORKER_STARTUP_TIMEOUT`
- `WORKER_EXITED`
- `WORKER_TIMEOUT_KILLED`
- `WORKER_PROTOCOL_FATAL`
- `WORKER_KILL_FAILED`
- `WORKER_SHUTDOWN_COMPLETED`

These are execution facts, never LiveFeed lifecycle aliases.

## 9. Frozen execution evidence shapes

The implementation must follow the exact field contracts defined by R3 for:

- `ResolvedProviderCommandOutcome`
- `ProviderWorkerLifecycleEvidence`
- `ProviderWorkerSupervisorConfig`
- `ProviderExecutionOutcome`
- `ProviderWorkerEvidenceKind`
- `ProviderExceptionDisposition`

The original immutable `ProviderCommand` is embedded/correlated as the command identity source rather than duplicating its identity fields into a second partial truth.

## 10. Frozen timeout/config completeness semantics

Every current `ProviderCommandType` requires one finite positive execution timeout.

The supervisor configuration also requires finite positive:

- startup timeout;
- graceful shutdown timeout;
- terminate join timeout;
- kill join timeout;
- parent command queue capacity;
- child DATA queue capacity;
- child PRIORITY queue capacity;
- supervisor observation inbox capacity;
- maximum frame bytes;
- explicit protocol version.

No numeric values are frozen here. Values are provider/config/benchmark evidence.

Missing/extra command timeout mapping relative to the current enum fails configuration mechanically.

## 11. Frozen provider exception rule

Default is `GENERATION_FATAL`.

Only an explicit provider-adapter classification backed by regression evidence may mark an exception family/context `WORKER_REUSABLE`.

Unknown exception text may not be string-matched into reusable authority.

Provider normal negative return/rejection is not automatically worker-fatal.

Timeout is always generation-fatal.

## 12. Frozen IPC topology

V0.1 preferred substrate:

- Python stdlib process supervisor;
- explicit `multiprocessing.get_context("spawn")`;
- one worker process per provider session;
- generation-local unidirectional Pipes;
- provider SDK/context created only inside child;
- no shared cross-generation `multiprocessing.Queue` or correctness-critical cross-process lock;
- bounded process-local queues/inboxes;
- fresh IPC on every worker generation;
- killed/dead generation IPC is disposable.

No Pebble/Loky/Toxiproxy runtime dependency is approved by this freeze.

## 13. Frozen child outbound model

Provider callback threads do not write IPC directly.

```text
provider callback threads -> bounded DATA queue
command/runtime evidence -> bounded PRIORITY queue
                           -> one sender thread
                           -> strict PRIORITY before DATA
                           -> sender assigns worker_event_seq
                           -> child event Pipe
```

`worker_event_seq` means transmitted wire order only.

DATA overflow -> explicit loss evidence.

PRIORITY overflow -> generation-fatal.

Required supervisor observation ingress loss -> generation-fatal via producer fault latch interpreted only by coordinator.

## 14. Frozen submit/shutdown admission model

`submit()` performs bounded nonblocking producer transport only.

A narrow producer-facing admission latch controls whether new submissions may enter local transport. Shutdown closes that admission latch before publishing shutdown intent.

The latch is not supervisor lifecycle state and does not grant callers terminal mutation authority.

Admitted but undispatched commands at shutdown are coordinator-terminalized as `CANCELLED_SHUTDOWN`.

## 15. Frozen LiveFeed integration seam

Future authoritative writer ingress conceptual union:

```text
ProviderEvent
ControllerIntent
ResolvedProviderCommandOutcome
ProviderWorkerLifecycleEvidence
```

Every accepted item that may influence controller/recovery interpretation receives one `local_enqueue_seq` from the same controller-local monotonic allocator and is globally merge-ordered before writer application.

Execution outcome history is derived/non-authoritative; it cannot remain a separately ordered truth.

Supervisor execution evidence may explain trust loss; it cannot manufacture trust.

## 16. Frozen callback anti-laundering rule

A child/provider callback is never stamped using the controller's opportunistically sampled current generation.

One worker generation has one immutable `controller_generation_binding` in V0.1.

Old-worker evidence remains old-generation evidence after controller recovery changes and is rejected by writer relevance policy.

No in-place rebind exists in V0.1.

## 17. Frozen external-library disposition

- Python 3.11 `ProcessPoolExecutor`: rejected as direct strict-timeout solution.
- Pebble: method/test reference only; no dependency approved.
- Loky: lifecycle/spawn reference only; no dependency approved.
- Toxiproxy: not needed for current P0; reconsider later for latency/jitter/asymmetric Currentness/Continuity fault work.
- existing Radar localhost transport proxy remains the controlled cut/restore harness for current provider semantics work.

## 18. Required implementation acceptance suite

The implementation must carry forward all acceptance cases from the Contract Candidate, R2, R3 and R4, including at minimum:

- startup readiness/hang timeout;
- normal command terminal exactly once;
- provider rejection semantics;
- deliberately unreturning command -> timeout -> PID confirmed dead;
- timeout/result/process-exit races;
- generation-local IPC disposal;
- no cross-generation replay;
- queue/inbox/frame overflow fail-closed paths;
- strict PRIORITY-before-DATA under flood;
- malformed/oversized protocol frames;
- shutdown idle/busy/hung/CLOSE hang;
- kill failure -> FATAL/no replacement;
- monotonic deadline vs wall-clock jumps;
- callback anti-laundering;
- immutable worker controller-generation binding;
- no provider object in parent pure tests;
- no orphan child after teardown;
- future command enum growth without timeout mapping fails mechanically.

## 19. Cross-platform promotion gate

Linux pure-supervisor tests run on every implementation PR.

Before Windows production promotion, a Windows CI job must prove:

- explicit spawn startup;
- startup hang kill;
- unreturning command hard timeout;
- exact owned worker PID/process death confirmation;
- generation-local IPC disposal;
- fresh replacement only after confirmed cleanup;
- hung shutdown kill;
- idempotent teardown;
- no orphan worker process.

A Linux-only green suite is not enough for Windows production promotion.

## 20. Provider Shadow promotion gates

Before Futu Shadow/CORE promotion:

- pin exact SDK/OpenD environment evidence;
- exact-version source/process-tree audit;
- prove no unexpected descendant survives worker death;
- benchmark JSON/frame/queue throughput on recorded provider fixtures;
- controlled Futu worker test using existing localhost transport proxy;
- prove parent/controller remains responsive through outage and dangerous synchronous RPC;
- prove provider worker timeout/kill is isolated;
- prove auto-reconnect/resubscribe never self-promotes LiveFeed trust.

## 21. Change control

This design is now frozen.

Implementation convenience may not silently change:

- identity ownership;
- single-coordinator rule;
- hard killability requirement;
- no-auto-replay rule;
- first-terminal-wins;
- global writer ingress ordering;
- immutable callback generation binding;
- strict priority evidence handling;
- default-fatal unknown exception policy;
- fail-closed configuration completeness;
- Windows promotion requirements.

Any proposed change to those requires an explicit design revision and adversarial review before code relies on it.

## 22. Next implementation slice

The first implementation slice must be deliberately narrow:

> **Slice A — contracts/config only**

Allowed:

- enums;
- immutable dataclasses;
- validation invariants;
- config completeness checks;
- serialization-neutral normalized payload freezing reuse;
- exact public-contract/mechanical tests;
- CI inclusion.

Forbidden in Slice A:

- multiprocessing worker;
- Futu imports;
- provider RPC calls;
- Pipes/queues/watchers;
- controller lifecycle behavior changes;
- Currentness/Continuity/LIVE;
- runtime dependency additions.

Only after Slice A is independently reviewed/validated may Slice B implement the pure fake-child supervisor state machine/process boundary.

## Governing sentence

> The provider worker may own execution; only the LiveFeed writer may own interpretation, and neither may invent trust.