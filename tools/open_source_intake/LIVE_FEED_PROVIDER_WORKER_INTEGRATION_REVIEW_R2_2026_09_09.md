# LiveFeed Provider Worker Supervisor — Integration / Concurrency Review R2

Status: DESIGN REVIEW R2. Non-production. Not frozen.

Reviewed against:

- authoritative `docs/LIVE_FEED_RELIABILITY_CONTRACT_V0_1.md`;
- current `src/services/live_feed/controller.py`;
- current `src/services/live_feed/commands.py`;
- Provider Worker Contract Candidate V0.1;
- Process-Isolated Supervisor Adversarial Review R1.

## R2 conclusion

Two more freeze blockers can be resolved at design level:

1. parent supervisor state must be single-writer/serialized internally so submit/result/timeout/process-exit/shutdown races do not depend on lock acquisition accidents;
2. any execution outcome that may later influence controller/recovery truth must enter the LiveFeed writer through the same global sequencing boundary as provider events and controller intents. The current separate command-result history staging is insufficient for future authoritative interpretation.

R2 also performs a source-level descendant-process audit of the public Futu SDK repository and downgrades that blocker to an implementation-version verification gate rather than an open architecture question.

## 1. Parent supervisor concurrency model

### Decision candidate: one supervisor coordinator owns all mutable supervisor state

The supervisor itself is not the authoritative market-state writer, but its execution state still requires one deterministic mutation owner.

Candidate architecture:

```text
submit callers -------------------------+
shutdown caller ------------------------|
child watcher / IPC decoder ------------|--> parent-local SupervisorInbox
                                        |        (thread-safe bounded queue)
                                        |
                                        v
                               SupervisorCoordinator
                               ONE state mutation owner
                                  |          |
                                  |          +-- timeout/deadline decisions
                                  +-- child command Pipe writer
```

Only `SupervisorCoordinator` may mutate:

- supervisor lifecycle state;
- current worker generation/process handle;
- in-flight command state;
- terminal outcome state;
- queue cancellation state;
- worker invalidation state;
- restart eligibility/fatal state.

Other threads are evidence/intent producers only.

This mirrors Radar's single-writer discipline without pretending the supervisor owns LiveFeed truth.

### Why not lock-shared terminal mutation

A design in which:

- watchdog thread commits TIMEOUT;
- IPC reader commits SUCCESS;
- shutdown thread commits cancellation;
- process watcher commits WORKER_EXITED;

all under one mutex is technically serializable but makes result ordering a lock-scheduling accident and increases the number of mutation-capable paths.

R2 rejects that pattern.

## 2. Supervisor event sources

Candidate parent-local inbox events:

- `SUBMIT_REQUEST`
- `SHUTDOWN_REQUEST`
- `CHILD_FRAME_OBSERVED`
- `CHILD_PIPE_EOF`
- `WORKER_PROCESS_EXITED`
- `WATCHER_PROTOCOL_ERROR`

Timeout does not need a producer thread. The coordinator computes the next monotonic deadline and uses timed inbox waiting.

### Child watcher responsibility

One child-watcher thread owns reading from the current generation's child->parent `Connection` and observing the current worker `Process.sentinel`.

Python 3.11 `multiprocessing.connection.wait()` supports readable `Connection` objects and `Process.sentinel` on both Unix and Windows, so the watcher can wait on both without POSIX-only signal assumptions.

The watcher never mutates supervisor state.

It:

1. waits on current generation event connection + process sentinel;
2. reads/validates frame boundaries enough to produce a raw observed-frame event;
3. stamps **parent-observed monotonic time** immediately after complete frame receipt;
4. enqueues the observation into `SupervisorInbox`;
5. enqueues process-exit/EOF evidence similarly.

Full semantic/identity/terminal-state authority stays with the coordinator.

## 3. Deterministic result-vs-timeout ordering

Coordinator scheduling delay must not decide whether a result beat its deadline.

Candidate rule:

- each dispatched command has immutable monotonic `execution_deadline_ns`;
- child watcher stamps `parent_observed_monotonic_ns` when a complete terminal frame is received;
- valid terminal result is timely only when:

```text
parent_observed_monotonic_ns < execution_deadline_ns
```

The execution interval is half-open: `[dispatch, deadline)`.

At exact deadline equality, timeout wins.

This matches Radar's broader preference for explicit half-open temporal semantics and avoids ambiguity.

### Queue delay does not steal execution budget

Execution deadline is computed at dispatch.

Parent-local queue wait is separately measured and may later gain its own queue-age policy; it does not silently consume provider RPC execution time.

## 4. Result-vs-process-exit ordering

A child may:

1. send a terminal frame;
2. exit immediately afterward.

When `multiprocessing.connection.wait()` indicates both the event connection and process sentinel are ready in one observation cycle, the watcher should drain available complete child frames before publishing process-exit evidence for that cycle.

Rationale:

- a valid terminal result already handed into IPC before process exit should not automatically become `WORKER_EXITED` merely because the process exited quickly;
- malformed/partial/EOF-without-terminal remains fail-closed.

Final terminal authority still uses first-terminal-wins and deadline comparison.

## 5. One writer to each IPC endpoint

Parent command Pipe:

- only SupervisorCoordinator writes.

Child event Pipe:

- only child IPC sender thread writes.

This removes cross-thread frame interleaving from both directions.

Provider SDK callback threads communicate only with child-local bounded queues.

## 6. Current controller integration gap

Current Slice-1 controller has four relevant ingestion concepts:

1. provider-event queues stamped with global `local_enqueue_seq`;
2. controller-intent queue stamped from the same global sequence;
3. command queue from writer toward future worker;
4. `_pending_command_results`, which are staged separately and materialized as history before the globally sorted provider/control batch.

That is safe for current Slice 1 because command results do not drive lifecycle/control-plane truth.

It is **not sufficient** for future LANE 3 execution outcomes that may influence reconciliation/recovery.

Example race:

```text
SUBSCRIBE command issued
STOP request accepted
provider SUBSCRIBE result returns
worker timeout/exit occurs
provider callback arrives
```

If execution outcomes have no global writer ingress sequence, future logic cannot reconstruct their relative order against STOP/provider/control events without guessing.

## 7. Integration seam decision candidate

### Add a producer-safe execution-evidence ingress, not a second writer

Future implementation should introduce a provider-neutral immutable execution-evidence type and producer entry point conceptually equivalent to:

```text
submit_execution_evidence(evidence)
```

Properties:

- thread-safe;
- bounded;
- nonblocking local enqueue;
- stamps from the **same controller global enqueue sequence** used by ProviderEvent and controller intents;
- enters the priority/global merge path;
- does not mutate authoritative state;
- only `process_pending()` may interpret/apply it.

This preserves frozen principle 14.

### Execution evidence categories

Candidate provider-neutral union:

1. `ResolvedProviderCommandOutcome`
2. `ProviderWorkerLifecycleEvidence`

Do not force worker timeout/crash/startup failure into `ProviderEventKind.ERROR`; those are execution-infrastructure facts, not necessarily provider-origin errors.

### `ResolvedProviderCommandOutcome`

Parent supervisor owns/correlates:

- immutable original `ProviderCommand`;
- `worker_generation`;
- terminal execution outcome enum;
- parent dispatch monotonic time;
- parent completion/terminal monotonic time;
- completion UTC audit time;
- normalized provider result/error evidence when present;
- diagnostic reason.

The child does not redefine command/controller identity.

### `ProviderWorkerLifecycleEvidence`

Candidate kinds:

- `WORKER_RUNTIME_STARTED`
- `WORKER_RUNTIME_READY`
- `WORKER_STARTUP_FAILED`
- `WORKER_STARTUP_TIMEOUT`
- `WORKER_EXITED`
- `WORKER_TIMEOUT_KILLED`
- `WORKER_PROTOCOL_FATAL`
- `WORKER_KILL_FAILED`

These are not LiveFeed lifecycle states.

They become writer-consumed evidence that later recovery policy may interpret.

## 8. Global ordering requirement

Execution evidence that can affect authoritative controller/recovery state must share one global ordering domain with:

- ProviderEvent;
- STOP;
- desired-registry mutation requests;
- control-plane state requests.

The exact internal queue layout may still use separate bounded priority queues for backpressure, but every accepted item must receive a sequence from the same monotonic controller-local sequence allocator and be merged before writer application.

No "materialize all command results first" shortcut may be used once command execution outcomes acquire state-transition semantics.

## 9. Existing command-result history compatibility

Current `command_results` history can remain diagnostic/audit storage if desired, but it must become a **derived sink** of writer-applied execution outcomes or otherwise remain explicitly non-authoritative.

Do not maintain two independently ordered command-result truths:

- one history list;
- one execution-outcome ingress.

Candidate rule:

> The globally sequenced execution outcome is the source evidence. Any command-result history is derived from it.

No production code change is made by this review.

## 10. Provider callback bridge and anti-laundering rule

Child provider frames carry `worker_generation` and provider-normalized payload, but a provider callback must eventually become a `ProviderEvent` carrying frozen controller-generation identity before reaching controller logic.

Anti-laundering invariant:

> Parent code must never read the controller's *current* generation at callback receipt time and stamp that value onto arbitrary child evidence.

That would let an old worker/session callback cross a recovery boundary and appear current.

Candidate binding model:

- each admitted provider worker/session execution context carries an immutable or explicitly controller-authorized `controller_generation_binding` established by integration/recovery logic;
- when converting a child provider frame into `ProviderEvent`, use that binding, not `controller.snapshot().controller_generation` sampled opportunistically at receipt;
- if controller recovery generation changes and the old binding is no longer relevant, existing writer-side relevance logic rejects the event;
- rebinding/issuing a new connection-generation authority must be an explicit controller/recovery action, never an SDK auto-reconnect side effect.

`worker_generation` remains checked at the supervisor boundary before conversion. It does not replace controller-generation relevance.

## 11. Worker-generation failure does not own controller generation

R2 confirms the candidate from the main contract:

- worker timeout/death invalidates `worker_generation`;
- supervisor emits globally sequenced execution evidence;
- controller writer consumes evidence;
- controller/recovery state machine decides whether its frozen connection/controller generation changes.

No direct `worker_generation -> controller_generation` increment rule is allowed.

This is required by frozen identity principle 10.

## 12. Supervisor -> child command identity

Each dispatch binds:

- immutable original `ProviderCommand`;
- current worker generation;
- execution deadline metadata owned by parent.

The child may use provider-relevant command fields to execute the SDK operation.

It may not change:

- runtime identity;
- provider identity;
- controller generation;
- desired registry revision;
- stream subscription epoch;
- SemanticStreamKey.

Terminal provider return is data attached to the parent-owned command, not a replacement command definition.

## 13. Futu descendant-process source audit

Public repository source search on the currently inspected `FutunnOpen/py-futu-api` revision found:

- substantial internal `threading.Thread` use for callback/network machinery;
- no `multiprocessing` usage from the repository code search performed in R2;
- one `subprocess.Popen` helper in `futu/__init__.py` used by `_pip_get_package_version()` to run `python -m pip show ...`;
- the inspected `__init__.py` defines `_check_package()` but does not call it in the normal import sequence shown there; active dependency checks use `_check_module()` instead.

R2 wording discipline:

> No intentional long-lived SDK child-process ownership was identified in the inspected public source paths. This is not proof that every dependency/version/runtime path can never create a subprocess.

Implementation gate:

- pin/record exact installed Futu SDK version/commit-equivalent evidence;
- repeat source search for `subprocess`, `multiprocessing`, process-launch helpers on that exact version;
- run a Shadow process-tree observation during worker startup/normal commands/timeout cleanup;
- if unexpected descendant process creation is observed, hard-killability claims are blocked until process-tree ownership is designed.

This resolves the architecture blocker to a validation/provider-version gate rather than assuming either safety or danger without evidence.

## 14. Internal Futu threads and process isolation

Futu's visible thread usage strengthens rather than weakens the process-isolation argument:

- provider callback/network threads remain inside the worker process;
- hard termination of the worker process removes those in-process provider threads together;
- parent controller/supervisor does not need to kill individual provider SDK threads;
- graceful CLOSE is still attempted under bounded shutdown when possible;
- if graceful provider thread cleanup hangs, process kill is the outer boundary.

This is not permission to terminate the external OpenD service, which remains independently managed.

## 15. Parent coordinator acceptance cases added by R2

Add permanent tests for:

1. result observed before deadline but processed by coordinator after deadline -> result still wins;
2. result observed at exact deadline -> TIMEOUT wins under half-open rule;
3. result observed after deadline -> TIMEOUT wins;
4. result frame + process sentinel ready together -> valid complete terminal frame inspected before WORKER_EXITED classification;
5. EOF without terminal result -> WORKER_EXITED;
6. concurrent submit/shutdown/result observations mutate supervisor state only via coordinator;
7. no test helper/thread may call terminal-state mutation directly outside coordinator context;
8. parent command Pipe has one writer owner;
9. current-generation provider frame converted with bound controller generation, not opportunistic current snapshot generation;
10. old generation binding remains stale after controller recovery changes;
11. execution outcome receives global writer enqueue sequence relative to STOP/provider events;
12. command-result history cannot reorder authoritative execution outcome.

## 16. R2 resolved blockers

The main Contract Candidate's remaining freeze items update as follows:

### Resolved in R2 at design level

- parent supervisor concurrent transition ownership -> single coordinator;
- result/timeout ordering -> parent-observed monotonic timestamp + half-open deadline;
- process-exit/result ordering -> drain complete frames before exit evidence in same readiness cycle;
- single-writer IPC endpoint ownership;
- integration seam -> globally sequenced execution evidence ingress to existing LiveFeed writer;
- command-result history authority -> derived/non-authoritative only;
- callback generation anti-laundering rule;
- Futu descendant-process concern -> exact-version source + Shadow process-tree validation gate.

### Still open before DESIGN:FROZEN

1. exact resolved execution-evidence dataclass/schema field types;
2. timeout configuration source/validation contract for every ProviderCommandType;
3. exact bounded queue/frame configuration ownership semantics (numeric values may remain config evidence rather than design constants);
4. provider exception taxonomy: reusable-worker vs generation-fatal;
5. exact writer-side interpretation boundary for execution outcomes — especially which outcomes alter failure/recovery state vs remain diagnostics;
6. Windows CI workflow mechanics for process-kill/orphan acceptance tests.

JSON codec throughput and exact SDK process-tree behavior move to validation gates, not architecture blockers, provided their fail-closed rules remain frozen.

## 17. R2 decision

`PROCESS-ISOLATED SINGLE-PROVIDER SUPERVISOR` remains preferred.

The design is now close enough to justify a **contract-shape R3**, but not yet production implementation.

Next R3 should freeze:

- execution evidence schemas/enums;
- supervisor config contract without arbitrary timeout numbers;
- exception/fatality classification default;
- writer interpretation authority matrix;
- CI acceptance topology.

Only after R3 adversarial review should the overall Provider Worker contract be considered for `DESIGN:FROZEN`.
