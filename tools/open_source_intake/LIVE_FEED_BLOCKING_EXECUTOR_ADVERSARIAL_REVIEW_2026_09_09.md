# LiveFeed LANE 3 — Process-Isolated Provider Supervisor Adversarial Review 2026-09-09

Status: DESIGN REVIEW R1. Non-production. Not frozen.

Reviewed candidate: `PROCESS-ISOLATED SINGLE-PROVIDER SUPERVISOR` from `LIVE_FEED_BLOCKING_EXECUTOR_HARVEST_BATCH_2026_09_09.md`.

## R1 conclusion

The process-isolation direction survives first-pass adversarial review, but the initial sketch was underspecified in three places that are load-bearing for real killability:

1. IPC must be **generation-scoped and disposable** because terminating a process while it uses multiprocessing pipes/queues can corrupt those communication objects.
2. Provider context construction itself needs a **startup hard deadline** because Futu context initialization is already a proven blocking-risk path.
3. A provider session should allow **one synchronous RPC in flight at a time**; queued commands stay in a bounded parent-local queue. This prevents the parent from writing more commands into a pipe while the child is stuck inside a prior synchronous call and matches the serialized nature of one provider session.

The design remains a candidate, not yet implementation-ready.

## A. IPC failure audit

### Finding A1 — `multiprocessing.Queue` must not be reused across a killed worker generation

Python's multiprocessing contract warns that killing a process while it is using a Queue/pipe can leave the communication object corrupted; shared locks/semaphores may also be left unusable.

Therefore the design may **not** use a long-lived multiprocessing Queue shared across worker generations and then kill/replace children behind it.

Invariant:

> A worker generation owns its own IPC endpoints. Once that worker is terminated or dies unexpectedly, every IPC endpoint associated with that generation is closed/discarded and is never reused by generation N+1.

Replacement generation = replacement IPC.

### Finding A2 — avoid multiprocessing feeder-thread ambiguity for the kill path

`multiprocessing.Queue` uses a background feeder thread. That creates extra shutdown/flush semantics exactly where Radar needs a simple hard boundary.

R1 candidate IPC:

- two generation-local `multiprocessing.Pipe(duplex=False)` pairs;
- parent -> child: command frames;
- child -> parent: result/provider-event frames;
- explicit `spawn` multiprocessing context;
- no multiprocessing Queue shared between parent and child;
- no cross-process Lock/Semaphore required by the protocol;
- on worker death/timeout: close/discard both Pipe generations before replacement.

The Pipe itself may be unusable after a hard kill. That is acceptable because the design never reuses it.

### Finding A3 — raw bytes + explicit envelope schema, not arbitrary provider objects

Candidate wire surface:

- `Connection.send_bytes()` / `recv_bytes()`;
- UTF-8 JSON envelope in V0.1;
- schema/version discriminator;
- bounded maximum frame size;
- explicit enum/string/timestamp serialization;
- provider SDK object never leaves child process;
- no raw arbitrary pickle payload accepted as provider evidence.

Benefits:

- wire contract is auditable;
- malformed/partial generation data fails schema validation;
- provider-specific classes cannot accidentally leak across process boundary;
- future replay fixtures can store/replay the exact normalized envelope shape.

If a worker is killed mid-frame and parent sees EOF/OSError/malformed data, the entire generation is failed closed and discarded.

### Finding A4 — one writer per Pipe endpoint

Futu callbacks may arrive on SDK-owned threads while a synchronous command is running.

Do not allow multiple callback threads to call child->parent `send_bytes()` concurrently.

Candidate child structure:

```text
SDK callback threads --put_nowait--> child-local event queues
command execution thread --put-->   child-local priority queue
                                      |
                                      v
                           one child IPC sender thread
                                      |
                                      v
                              child->parent Pipe
```

The queues inside this diagram are **ordinary in-process `queue.Queue`/deques**, not multiprocessing queues. They disappear with the child on kill.

One sender thread owns the outbound Pipe endpoint and emits monotonically sequenced envelopes.

## B. Child outbound backpressure audit

### Finding B1 — market-data callbacks must not block behind IPC

Provider callback threads remain minimal/nonblocking.

Candidate child outbound lanes:

- PRIORITY: worker lifecycle, command terminal result, disconnect/error/control evidence;
- DATA: normalized market-data events.

Both are bounded and share one `worker_event_seq` counter so the sender can preserve deterministic relative ordering when needed.

If DATA is full:

- reject/drop according to explicit harness/adapter policy;
- accumulate an explicit loss counter/finding;
- never silently pretend continuity survived.

If PRIORITY cannot accept a command terminal/lifecycle event:

- classify worker protocol/health as failed;
- parent deadline/process-liveness supervision remains the fail-closed safety net;
- never silently discard a required terminal result and keep the worker trusted.

Exact capacities remain configuration/design work; this review does not invent thresholds.

## C. Parent command handoff audit

### Finding C1 — `submit()` cannot directly block on a child pipe write

The frozen executor protocol says local `submit(command)` is nonblocking with respect to the provider SDK.

Candidate parent path:

```text
submit(command)
    -> validate immutable command
    -> put_nowait into bounded parent-local queue
    -> return
```

The supervisor owns draining that queue toward the child.

### Finding C2 — one synchronous provider RPC in flight per provider session

Do not pipeline multiple synchronous Futu RPCs into one child that can execute only one at a time.

Candidate invariant:

> `max_provider_rpc_inflight_per_worker_generation = 1`.

While one command is RUNNING:

- later commands remain in the bounded parent-local queue;
- parent does not keep filling the child Pipe;
- timeout applies to the actual running command, not time spent waiting locally before dispatch.

Queue wait time should remain separately observable so starvation is not hidden.

This also simplifies exactly-once terminal-result and kill semantics.

## D. Worker startup audit

### Finding D1 — provider initialization needs its own hard deadline

Futu `OpenQuoteContext` construction has already demonstrated blocking risk.

Therefore worker startup is not complete when `Process.start()` succeeds.

Candidate startup state:

```text
spawn child generation N
    -> child imports adapter/SDK
    -> child installs internal emitter
    -> child creates provider context
    -> child installs provider handlers
    -> child emits WORKER_READY
```

Parent owns a monotonic `startup_deadline`.

If `WORKER_READY` is not accepted before the deadline:

- mark generation N `STARTUP_TIMEOUT`;
- terminate/kill N;
- discard N IPC;
- do not issue provider commands to N;
- replacement/retry is a recovery-policy decision, not automatic LIVE success.

A `WORKER_READY` event means only the isolated execution runtime is ready to accept commands. It does **not** mean provider transport, authentication, subscription, Currentness, Continuity, or LIVE is qualified.

## E. Deadline / clock audit

All execution deadlines use `time.monotonic_ns()` or equivalent monotonic clock injected for tests.

Do not store a wall-clock timestamp and later subtract wall time to decide timeout.

Keep both when useful:

- UTC timestamp for audit/reporting;
- monotonic deadline for timeout decisions.

Permanent test: simulated wall-clock jump must not change command expiration behavior.

## F. Hard kill sequence audit

Candidate parent timeout sequence:

1. atomically transition command terminal state to `TIMEOUT` if still RUNNING;
2. record timeout evidence with command + worker generation identity;
3. mark worker generation invalid/stale immediately;
4. stop dispatching any new command to that worker;
5. close/discard parent references to generation-specific IPC as appropriate;
6. `terminate()` worker;
7. bounded `join()`;
8. if still alive, `kill()` where platform distinction exists;
9. bounded final `join()`;
10. verify `is_alive() == False` before creating replacement generation;
11. close the dead `Process` handle after exit;
12. create entirely new IPC endpoints for replacement.

If the OS process cannot be confirmed dead after the hard-kill policy:

- supervisor enters FATAL/UNAVAILABLE;
- do not spawn unlimited replacements beside an unkillable old worker;
- require operator/process-level recovery.

No infinite retry loop inside the executor.

## G. Descendant-process audit

Python process termination does not automatically terminate descendants.

R1 rule:

> ProviderWorker V0.1 must not intentionally spawn child processes.

Futu/OpenD is an independently managed external service, not a child the worker is allowed to start/manage.

Before implementation promotion, provider adapter code must be audited for child-process creation. If a future provider requires descendants, the supervisor design must grow an OS-level process-tree/job boundary before claiming hard killability.

Do not assume killing PID N proves its entire execution tree is gone.

## H. Result/timeout race audit

Parent owns immutable in-flight record:

- `ProviderCommand` identity;
- worker generation;
- dispatch monotonic time;
- deadline monotonic time;
- state (`QUEUED`, `DISPATCHED`, `RUNNING`, terminal);
- terminal outcome if any.

First-terminal-wins:

- result accepted before timeout transition -> result is terminal; timeout no-ops;
- timeout transition wins -> later result from that command/generation cannot become current terminal truth;
- worker death -> unresolved running command receives explicit indeterminate worker-exit outcome unless already terminal.

No second success/failure event may overwrite a terminal command state.

A late result may be retained only as diagnostic evidence if it can be parsed safely; it has no current authority.

## I. Generation model audit

Keep these orthogonal:

1. `runtime_instance_id` — process/runtime identity of Radar;
2. `controller_generation` — authoritative LiveFeed controller/recovery identity;
3. `worker_generation` — isolated provider process incarnation;
4. `desired_registry_revision` — desired-subscription set version;
5. `stream_subscription_epoch` — one stream remove/re-add incarnation;
6. provider-native connection/callback identifiers — diagnostic unless separately proven stable.

No mechanical equality or derived mapping between these identities.

A timeout of one worker generation invalidates that worker's evidence. It does not by itself increment or define controller generation unless the controller/recovery design explicitly chooses that transition.

## J. Child protocol envelope candidate

Every child->parent frame should minimally carry:

- `protocol_version`;
- `envelope_type`;
- `runtime_instance_id`;
- `provider_id`;
- `worker_generation`;
- `worker_event_seq`;
- observed UTC timestamp;
- observed monotonic timestamp if meaningful within the child only;
- type-specific normalized payload.

Command terminal envelopes additionally correlate `command_id`.

Parent resolves `command_id` against its immutable in-flight `ProviderCommand`; it does not trust the child to redefine command identity.

ProviderEvent adaptation then attaches the controller-generation/desired/stream identities from the appropriate governed source rather than manufacturing them from provider-native connection IDs.

## K. Protocol error policy

Any of these are fail-closed worker protocol errors:

- unsupported protocol version;
- malformed JSON/schema;
- unknown envelope type;
- missing worker generation;
- event sequence invalid under the frozen rule chosen later;
- wrong runtime/provider identity;
- terminal result for unknown command id;
- impossible duplicate terminal result;
- frame above configured maximum.

A protocol error does not become a provider success/failure guess.

Whether every protocol error kills the worker or only quarantines one frame is still a freeze decision. Security/identity violations should default toward generation invalidation.

## L. Windows spawn audit

Use explicit `multiprocessing.get_context("spawn")` for the worker implementation rather than inheriting platform-default fork behavior.

Consequences to test:

- worker target must be module-level/importable;
- startup configuration must be serializable;
- provider context is constructed in the child, never pickled from parent;
- tests/entrypoints must be safe under Windows spawn/import semantics;
- teardown must close every Process/Connection handle;
- no reliance on POSIX signals for correctness.

The hard-kill acceptance suite must run on Windows CI if this becomes a production Windows capability.

## M. Mature-library comparison after R1

### Pebble

Still useful as a method reference for task timeout -> worker stop -> replacement.

However the specialized requirements that remain even with Pebble are substantial:

- one provider session/worker identity;
- long-lived provider context;
- provider callback IPC;
- child outbound backpressure/loss semantics;
- Radar worker generation;
- command identity correlation;
- Currentness/Continuity/recovery separation.

R1 result: **no dependency promotion yet**.

### Loky

Useful for spawn/reusable/broken-worker lifecycle reference. It still does not directly own Radar's per-command deadline + stateful provider session semantics.

R1 result: **reference only**.

### Stdlib specialized supervisor

After the IPC review, stdlib primitives remain viable **as building blocks**, not as `ProcessPoolExecutor` direct use:

- `multiprocessing.get_context("spawn")`;
- `Process`;
- generation-local `Pipe`/`Connection`;
- process sentinel / bounded join;
- parent-local `queue.Queue`;
- child-local `queue.Queue`;
- monotonic watchdog.

This candidate has more Radar-owned code but maps directly to the session/identity contract and introduces no runtime dependency.

## R1 unresolved blockers before design freeze

1. Exact IPC envelope schema and max-frame policy.
2. Exact parent supervisor state machine.
3. Exact child worker lifecycle state machine.
4. Command timeout policy ownership and coverage for every `ProviderCommandType`.
5. Terminal outcome vocabulary (`SUCCESS`, provider failure, timeout, worker-exit, shutdown cancellation, protocol failure).
6. Relationship between worker invalidation and controller recovery generation.
7. Child outbound priority/data capacity and loss policy.
8. Whether provider callback data can be safely JSON-normalized at required throughput.
9. Windows CI hard-kill/orphan-process test strategy.
10. Audit that the chosen Futu adapter path does not spawn descendants.

## R1 decision

`PROCESS-ISOLATED SINGLE-PROVIDER SUPERVISOR` remains the preferred design candidate.

The preferred implementation substrate after R1 is **stdlib specialized supervisor first**, with Pebble held as a comparison/reference rather than added now.

Reason: the difficult code is Radar-specific session identity, callback transport, result authority, and recovery separation; a generic process pool removes only part of the kill/restart mechanism while introducing another lifecycle abstraction that would still need to be wrapped.

No production code should be written until the unresolved blockers above are turned into an explicit frozen contract and adversarial acceptance suite.
