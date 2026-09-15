# Open-Source Intake — LiveFeed Production LANE 3 Blocking Executor Harvest Batch 2026-09-09

Status: DESIGN CANDIDATE / HARVEST LEDGER. Non-production. Not frozen.

## Problem

LiveFeed's frozen negative constraint is already clear:

> A potentially blocking provider SDK call must never execute on the authoritative controller writer thread.

Slice 1 structurally separates controller command submission from provider execution, but the current production boundary is incomplete:

- `ProviderCommandExecutor` is only a Protocol;
- `FakeProviderCommandExecutor` is deliberately synchronous and test-only;
- `run_command_worker_once()` is a deterministic test helper, not process isolation;
- the Blocking Execution Model explicitly leaves thread timeout vs process isolation open;
- Futu research has already produced real long blocking incidents during context construction and `query_subscription()` under outage.

This is a proven reliability gap, not hypothetical hardening.

## Requirements derived before choosing tooling

A production LANE 3 implementation must satisfy all of these:

1. `submit(command)` returns after bounded local handoff; it never waits for a provider SDK RPC.
2. A provider call that never returns must be terminable by a parent-owned boundary.
3. Timeout must terminate the **execution capability**, not merely stop the parent from waiting.
4. The authoritative LiveFeed writer must remain able to process events while LANE 3 is blocked/restarting.
5. Provider session/context ownership must be unambiguous.
6. Provider SDK callbacks must never mutate controller truth directly; they remain producer evidence only.
7. A timed-out/killed worker generation is permanently stale. Late results/evidence from it cannot regain authority.
8. Command timeout/failure/worker death become explicit immutable evidence, never silent disappearance.
9. Shutdown is bounded and idempotent. A hung CLOSE cannot hold process shutdown forever.
10. The mechanism must work under the repository's current Python 3.11 target and Windows deployment reality.
11. No provider object is assumed safely picklable. Create/own provider contexts inside the worker process.
12. Raw provider payloads are normalized/frozen before crossing into authoritative state.
13. Queue/IPC capacity and failure semantics are explicit; no unbounded hidden backlog.
14. Wall-clock jumps cannot extend command deadlines; watchdog deadlines use monotonic time.
15. Recovery policy remains above the executor. Killing/restarting a worker does not itself mean LIVE recovery.

## Candidate: stdlib `concurrent.futures.ProcessPoolExecutor` on Python 3.11

Disposition: `REJECT DIRECT FOR STRICT TIMEOUT`.

Useful properties:

- true separate processes;
- standard Future API;
- initializer support;
- `max_tasks_per_child` in Python 3.11.

Blocking problem:

- a Future already running cannot be cancelled;
- `cancel_futures=True` only cancels work that has not started;
- normal shutdown semantics do not provide a Python-3.11 public per-running-task kill primitive.

Therefore `future.result(timeout=T)` is not a hard provider-call timeout. It bounds the caller's wait while the stuck child may remain stuck.

This fails Requirement 2/3 by itself.

## Candidate: noxdafox/pebble

- URL: https://github.com/noxdafox/pebble
- License: LGPL-3.0.
- Disposition: `ADAPT / TEST-REUSE CANDIDATE`, not automatic dependency.

High-value method:

- `ProcessPool.schedule(..., timeout=...)` tracks a running task deadline;
- on timeout, Pebble can stop the worker process associated with the task;
- the pool then recreates expired workers;
- worker/channel handling is explicitly designed around process death rather than pretending a Python thread can be safely cancelled.

Why direct adoption is not yet justified:

1. Futu is a stateful, long-lived session with callbacks/reconnect state, not an ordinary stateless function-call workload.
2. A generic multi-worker pool could accidentally move commands for one provider session between worker processes unless constrained to one worker/session.
3. Worker replacement implies transport/session replacement and must be reflected in Radar generation identity, not hidden as a pool implementation detail.
4. Provider callbacks need a dedicated child->parent evidence path independent of ordinary task return values.
5. Killing a process while IPC is active requires explicit stale-generation/drop/recovery semantics even if the library handles its own internal channels correctly.
6. Adding an LGPL runtime dependency is not justified until it materially reduces specialized supervisor code rather than wrapping it.

Harvest the kill-on-timeout and worker-replacement semantics first; do not copy source.

## Candidate: joblib/loky

- URL: https://github.com/joblib/loky
- License: BSD-3-Clause.
- Disposition: `METHOD / REFERENCE`, not direct solution to the hard deadline.

Useful methods:

- robust cross-platform process spawning;
- reusable executor lifecycle;
- broken-worker detection and pool repair;
- explicit `kill_workers` path during executor replacement/shutdown.

Gap for this problem:

- its public worker `timeout` is primarily an **idle worker lifetime** control;
- it does not, by that parameter alone, provide the required per-provider-command execution deadline that automatically kills a currently stuck SDK call.

Useful as lifecycle/reference evidence, not sufficient as the LANE 3 contract.

## Radar-native design candidate

### One provider session = one isolated worker process

Do not model LANE 3 as a generic CPU task pool.

Model it as a supervised provider runtime:

```text
LiveFeedController writer
    |
    | local immutable ProviderCommand
    v
ProviderWorkerSupervisor  (parent process)
    |
    | bounded IPC command channel
    v
ProviderWorkerProcess  generation N
    |
    +-- owns Futu/OpenQuoteContext
    +-- owns provider synchronous RPC execution
    +-- owns SDK callback handlers
    |
    | immutable normalized result/event IPC
    v
Parent ingress staging
    |
    v
LiveFeedController writer
```

The provider SDK object never crosses process boundaries.

### Parent-owned supervisor state

Candidate facts owned by the supervisor, not by the authoritative controller:

- worker PID/process handle;
- `worker_generation` / provider-worker incarnation;
- worker lifecycle (`STARTING`, `READY`, `STOPPING`, `DEAD`);
- bounded command channel;
- bounded result/event channel or equivalent framed IPC;
- in-flight command table keyed by `command_id`;
- issued monotonic timestamp/deadline per command;
- terminal-result state so one command cannot complete twice;
- child heartbeat/process-liveness evidence if later needed;
- restart count / diagnostics.

These are execution facts. They do not define LIVE health by themselves.

### Child worker ownership

The child process:

1. starts under explicit spawn semantics;
2. imports/initializes the provider SDK inside the child;
3. creates the provider context inside the child;
4. installs SDK callbacks that normalize and publish provider evidence over child->parent IPC;
5. serially executes provider commands for that one session;
6. never writes Radar authoritative state;
7. emits normalized command completion evidence;
8. can be terminated wholesale by the parent if one provider call exceeds deadline.

### Hard-timeout path

Candidate sequence:

```text
command C issued under worker_generation=N
    -> child begins synchronous provider RPC
    -> monotonic deadline expires
    -> supervisor marks C terminal = TIMEOUT
    -> supervisor emits immutable timeout evidence for C
    -> supervisor kills generation N worker process
    -> ALL later evidence carrying worker_generation=N is stale
    -> supervisor records worker termination
    -> replacement generation N+1 may be created only under recovery policy
    -> reconnect/auth/replay/currentness/continuity qualification occurs above executor layer
```

The timeout does **not** leave the old process running in the background.

### First-terminal-wins rule

Race to handle explicitly:

- provider result and timeout can become observable nearly simultaneously.

Requirement:

> Exactly one terminal command outcome becomes authoritative execution evidence.

Candidate rule:

- parent supervisor owns command terminal state;
- first accepted terminal transition wins;
- a late result after TIMEOUT is retained only diagnostically or dropped under explicit stale-generation policy;
- killing the timed-out worker makes the broader session generation stale as well.

### Worker death without a known timed-out command

If the child exits unexpectedly:

- do not infer provider success/failure for an in-flight RPC;
- unresolved in-flight commands become an explicit `WORKER_EXITED` / indeterminate execution outcome;
- session/transport trust is invalidated;
- restart begins from a new worker generation;
- controller recovery remains fail-closed until later qualification.

### Shutdown

Candidate bounded sequence:

1. stop accepting new provider commands;
2. enqueue/attempt graceful provider close only under a bounded deadline;
3. if the worker exits, complete cleanup;
4. if close hangs or deadline expires, terminate the worker process;
5. close parent IPC endpoints;
6. repeated shutdown remains safe;
7. post-stop evidence from an old worker cannot resurrect controller lifecycle.

This composes with existing Case 20 rather than replacing it.

## Identity audit triggered by this design

Current `ProviderCommand` already carries:

- runtime instance;
- provider id;
- controller generation;
- desired registry revision;
- command id;
- command type;
- optional stream subscription epoch;
- optional semantic stream key.

Current `ProviderCommandResult` carries only a subset directly:

- command id/type;
- succeeded;
- controller generation;
- desired registry revision;
- completion time/error/raw payload.

Before implementation, decide explicitly whether result evidence:

A. remains minimal and is always correlated against a parent-owned immutable issued-command record by `command_id`; or
B. carries the full identity itself, including runtime/provider/stream incarnation.

Do not accidentally create two partially authoritative identity sources.

Recommended candidate: the supervisor retains an immutable in-flight `ProviderCommand` record and emits a **resolved envelope** containing both command identity and normalized terminal result. The controller consumes the resolved envelope, never an uncorrelated provider return.

This also provides a natural place to attach `worker_generation` without conflating it with `controller_generation` or `stream_subscription_epoch`.

## New identity invariant

Three generations are different and must remain different:

1. `controller_generation` — Radar controller/recovery identity;
2. `worker_generation` — isolated provider-process incarnation;
3. `stream_subscription_epoch` — one semantic stream's remove/re-add incarnation.

Never derive one mechanically from another.

A worker may die/restart while the controller is still evaluating recovery, and a stream may be removed/re-added without a worker restart.

## Why thread timeout is rejected

Moving the blocking SDK call to a normal thread protects the single writer but does not create a kill boundary.

If an SDK/C-extension call never returns:

- Python cannot safely kill that one running thread;
- worker capacity may be permanently consumed;
- shutdown may hang waiting for the thread;
- repeated failures can accumulate stuck threads/resources.

Therefore a plain `ThreadPoolExecutor + future.result(timeout=...)` is specifically not an acceptable production answer.

## Validation plan before implementation promotion

### Pure supervisor tests with a fake child process

Permanent tests should include:

1. normal command completes once;
2. command exceeds deadline -> worker terminated -> TIMEOUT exactly once;
3. late result racing timeout cannot become second terminal result;
4. worker crash mid-command -> explicit indeterminate outcome;
5. old worker-generation result rejected after replacement;
6. new worker-generation result accepted only when other command identity matches;
7. bounded command queue fails explicitly on overflow;
8. child/result channel break is observable;
9. shutdown during idle is bounded/idempotent;
10. shutdown during normal command is bounded;
11. shutdown during hung command kills worker and completes;
12. STOP plus old callback cannot resurrect state;
13. worker restart never implies LIVE;
14. monotonic deadline unaffected by wall-clock jump fixture;
15. no provider SDK import/object required in parent supervisor unit tests.

### Killability proof

Use a deliberately unreturning child command (`while True` / blocking event) and assert:

- parent deadline is bounded;
- worker PID is no longer alive after timeout cleanup;
- replacement worker can process a later control command;
- no orphan child remains after test teardown.

This is the acceptance test that stdlib `Future.result(timeout=...)` alone cannot satisfy on Python 3.11.

### Provider Shadow validation later

Only after pure isolation tests pass:

- run controlled Futu/OpenD context inside the isolated worker;
- prove normal subscribe/query path;
- induce existing local-proxy transport cut;
- prove parent remains responsive;
- prove a dangerous synchronous RPC cannot freeze the parent/controller;
- prove timeout kills/replaces only the provider worker;
- verify cleanup and no orphan OpenD/client child processes;
- never treat transport/session recovery as LIVE qualification.

## Current recommendation

`DESIGN CANDIDATE: PROCESS-ISOLATED SINGLE-PROVIDER SUPERVISOR`.

Do **not** implement a production adapter yet.

Do **not** add Pebble/Loky dependencies yet.

Next gate is a focused design/adversarial review of:

- IPC primitive and framing;
- parent/child ownership;
- worker-generation identity;
- exactly-once terminal command semantics;
- timeout kill/restart semantics;
- shutdown semantics;
- Windows spawn/cleanup behavior;
- whether a mature process-management dependency actually removes enough specialized code to justify itself.

Only after this design passes should it move from Harvest ledger into an implementation PR.

## Governing rule

> A timeout is real only if the stuck execution capability is bounded, not merely the caller's patience.
