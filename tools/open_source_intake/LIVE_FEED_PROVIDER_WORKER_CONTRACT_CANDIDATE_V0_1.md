# LiveFeed Provider Worker Supervisor Contract Candidate V0.1

Status: **DESIGN CANDIDATE — NOT FROZEN / NON-PRODUCTION**

Purpose: turn the proven LANE 3 blocking-risk gap into an explicit, reviewable execution contract before any production provider adapter or worker implementation is written.

This candidate is subordinate to the authoritative frozen `docs/LIVE_FEED_RELIABILITY_CONTRACT_V0_1.md`. It may add execution-layer detail only where that contract is silent. It may not weaken, reinterpret, or replace frozen provider/controller authority, identity, Currentness, Continuity, RecoveryCandidate, or LIVE rules.

## 1. Scope

This contract candidate owns only the execution boundary for potentially blocking provider SDK work:

- isolated provider worker process lifecycle;
- bounded parent-local command handoff;
- command dispatch and terminal execution evidence;
- hard execution deadlines;
- worker death/kill/replacement mechanics;
- child-to-parent normalized evidence transport;
- execution-layer generation identity;
- bounded shutdown;
- protocol integrity.

It does **not** own:

- desired subscription truth;
- `desired_registry_revision` mutation;
- connection/recovery generation policy;
- stream subscription intent epoch policy;
- subscription reconciliation policy;
- DeliveryMode qualification;
- Currentness;
- Continuity;
- RecoveryCandidate;
- final LiveFeed health aggregation;
- LIVE promotion;
- trading/strategy decisions.

## 2. Governing invariants

PWS-01. The authoritative LiveFeed controller writer never calls a provider SDK operation directly.

PWS-02. `ProviderCommandExecutor.submit()` performs only bounded local handoff. It never waits for provider RPC completion.

PWS-03. A provider SDK call that does not return must be terminable by a parent-owned OS-process boundary.

PWS-04. A timeout is not satisfied by timing out the caller's wait while the provider call keeps running. The stuck execution capability itself must be invalidated and killed.

PWS-05. One provider session/context is owned by exactly one provider worker process generation.

PWS-06. Provider SDK objects never cross the process boundary.

PWS-07. Provider callbacks are evidence producers only. Neither child callbacks nor the supervisor mutate authoritative controller truth directly.

PWS-08. Every worker generation owns fresh IPC endpoints. IPC from a dead/killed generation is disposable and is never reused by a replacement generation.

PWS-09. One synchronous provider RPC may be RUNNING per worker generation at a time.

PWS-10. Commands waiting behind a RUNNING provider RPC remain in a bounded parent-local queue; they are not pipelined into a child that may be blocked.

PWS-11. No queued or in-flight provider command is automatically replayed across worker-generation replacement.

PWS-12. Exactly one terminal execution outcome may win for one `command_id`.

PWS-13. Worker restart is infrastructure recovery evidence only. It never implies transport recovery, subscription recovery, Currentness, Continuity, or LIVE.

PWS-14. `runtime_instance_id`, frozen connection/controller generation identity, `worker_generation`, `desired_registry_revision`, and `stream_subscription_epoch` remain distinct identities.

PWS-15. Provider-native connection/callback IDs remain diagnostic unless separately proven by the Provider Semantic Contract. They cannot define Radar generations by convenience.

PWS-16. All execution/startup deadlines are decided with a monotonic clock. UTC timestamps exist for audit, not elapsed-time authority.

PWS-17. Shutdown is bounded and idempotent even if provider CLOSE or context cleanup blocks.

PWS-18. Any UNKNOWN execution fact stays UNKNOWN/INDETERMINATE. A worker crash or protocol failure must never be translated into provider success or rejection by guess.

PWS-19. Child process termination failure is a fatal execution-boundary condition. The supervisor must not create unbounded replacement processes beside an old worker it cannot prove dead.

PWS-20. V0.1 provider workers must not intentionally spawn descendant processes. A provider requiring descendants needs an explicit process-tree/job-control design before hard-killability may be claimed.

## 3. Identity model

### 3.1 Existing frozen identities remain authoritative in their own domains

- `runtime_instance_id`: Radar runtime/process identity.
- frozen connection/controller generation identity: authoritative recovery/connection incarnation owned by the LiveFeed controller/integration contract.
- `desired_registry_revision`: desired-set history.
- `stream_subscription_epoch`: controller intent incarnation for one semantic stream.
- `SemanticStreamKey`: exact semantic stream identity.

### 3.2 New execution-layer identity

`worker_generation`

Definition: monotonically increasing, supervisor-local incarnation of the isolated provider worker process for one provider runtime.

It answers only:

> Which isolated provider execution process produced this evidence?

It does **not** answer:

- which provider transport connection attempt produced the evidence;
- whether the provider session is current;
- whether desired subscriptions were reconciled;
- whether one stream incarnation is bound;
- whether controller recovery advanced;
- whether LIVE is qualified.

### 3.3 No identity collapse

Forbidden equivalences include:

```text
worker_generation == controller/connection_generation
worker_generation == provider_connection_attempt_id
worker_generation == stream_subscription_epoch
worker_generation == desired_registry_revision
provider SDK conn_id == any Radar-owned generation
```

Numeric equality by coincidence carries no semantic meaning.

## 4. Parent Supervisor state machine

Candidate public-to-executor state vocabulary:

- `ABSENT` — no worker process exists.
- `STARTING` — a worker process exists but has not completed worker-runtime initialization.
- `IDLE` — worker runtime is initialized and no provider command is RUNNING.
- `BUSY` — exactly one provider command is RUNNING.
- `STOPPING` — shutdown has begun; no new commands may be accepted for dispatch.
- `DEAD` — no trusted/alive worker generation is available.
- `FATAL` — supervisor invariant or killability failure prevents safe automatic continuation.

`IDLE` deliberately avoids the word `READY`. It means only execution-runtime availability, not market/provider readiness.

### 4.1 Legal transitions

```text
ABSENT   -> STARTING   explicit spawn
STARTING -> IDLE       valid WORKER_RUNTIME_READY accepted before startup deadline
STARTING -> DEAD       startup failure / startup timeout / worker exit
STARTING -> STOPPING   shutdown request

IDLE     -> BUSY       one queued command dispatched
IDLE     -> STOPPING   shutdown request
IDLE     -> DEAD       unexpected worker exit / fatal worker protocol invalidation

BUSY     -> IDLE       accepted non-worker-fatal terminal outcome
BUSY     -> DEAD       TIMEOUT / worker exit / worker-fatal protocol failure
BUSY     -> STOPPING   shutdown request

STOPPING -> DEAD       graceful exit or confirmed hard termination

DEAD     -> STARTING   explicit recovery policy chooses replacement generation

ANY      -> FATAL      old worker cannot be proven dead after hard-kill policy;
                      supervisor internal identity/terminal-state invariant is violated;
                      or execution integrity is otherwise unresolvable
```

`FATAL` has no automatic transition back to `STARTING` in V0.1.

### 4.2 State invariants

- `BUSY` implies exactly one in-flight command state is `RUNNING` for the current worker generation.
- `IDLE` implies zero `RUNNING` commands for the current worker generation.
- `DEAD`/`FATAL` implies no new provider command dispatch.
- `STOPPING` rejects new submit/dispatch work according to explicit shutdown-cancellation semantics below.
- no state in this machine maps directly to `LifecycleState.LIVE`.

## 5. Child Provider Worker state machine

Candidate child lifecycle vocabulary:

- `BOOTING`
- `IDLE`
- `EXECUTING`
- `EXITING`
- `EXITED`

Legal transitions:

```text
BOOTING    -> IDLE       SDK/context/handlers initialized; runtime-ready envelope emitted
BOOTING    -> EXITING    initialization failure or shutdown instruction when serviceable
BOOTING    -> EXITED     crash/process termination

IDLE       -> EXECUTING  one command accepted
IDLE       -> EXITING    graceful shutdown
IDLE       -> EXITED     crash/process termination

EXECUTING  -> IDLE       command call returns and terminal envelope is handed to child outbound lane
EXECUTING  -> EXITING    graceful path only if provider call has returned
EXECUTING  -> EXITED     parent hard-kills or process crashes

EXITING    -> EXITED     child cleanup completes
```

The parent never depends on the child successfully transitioning out of `EXECUTING`; that is the reason the parent owns a hard kill boundary.

Provider callback threads may produce normalized evidence while child state is `IDLE` or `EXECUTING`. They never execute controller logic.

## 6. Parent command lifecycle

Candidate parent-owned command states:

- `QUEUED`
- `DISPATCHED`
- `RUNNING`
- terminal state

`ProviderCommand` remains the immutable issued intent record. The supervisor stores it alongside execution metadata rather than asking the child to redefine command identity.

### 6.1 Queueing

`submit(command)`:

1. validates immutable command shape/identity;
2. rejects if supervisor cannot accept new work;
3. performs `put_nowait` into a bounded parent-local queue;
4. records local queue ingress monotonic time;
5. returns without provider SDK interaction.

Queue overflow is explicit. No silent drop and no unbounded queue.

### 6.2 Dispatch

A command may dispatch only when:

- supervisor is `IDLE`;
- current worker generation is alive and runtime-initialized;
- no command is `RUNNING`;
- command still passes supervisor-side structural validation.

At dispatch:

- bind the command to the current `worker_generation`;
- record dispatch monotonic time;
- compute finite execution deadline from the command timeout policy;
- send exactly one command envelope to the child;
- transition supervisor to `BUSY`.

Execution timeout starts at dispatch, not while the command waits in the local queue.

Queue wait duration is separately observable.

### 6.3 No cross-generation replay

If a worker dies or is killed:

- the RUNNING command receives its appropriate terminal outcome;
- commands that were never dispatched remain parent-local but **must not be automatically dispatched to a replacement generation as if nothing changed**;
- they must be explicitly revalidated/reissued under recovery policy or terminally cancelled according to the final integration design.

Candidate V0.1 conservative rule:

> On worker-generation invalidation, cancel all currently queued provider commands with `CANCELLED_GENERATION_INVALIDATED`. The authoritative controller/recovery layer decides which current intents require new commands under current truth.

This prevents executor-owned replay from laundering stale desired-registry or stream-incarnation intent across recovery.

## 7. Terminal command outcome vocabulary

Candidate terminal enum:

- `SUCCEEDED`
- `PROVIDER_REJECTED`
- `PROVIDER_EXCEPTION`
- `TIMEOUT`
- `WORKER_EXITED`
- `PROTOCOL_ERROR`
- `CANCELLED_SHUTDOWN`
- `CANCELLED_GENERATION_INVALIDATED`

### 7.1 Semantics

`SUCCEEDED`
- provider call returned a locally successful administrative result according to provider adapter normalization.
- It does not mean subscription confirmation, data-plane progress, Currentness, Continuity, or LIVE.

`PROVIDER_REJECTED`
- provider call returned an explicit provider/business rejection or negative administrative result.

`PROVIDER_EXCEPTION`
- provider SDK invocation returned by raising/producing a locally captured exception without killing the worker generation, if adapter policy classifies the worker runtime as still trustworthy enough to continue.
- This classification must be provider-adapter explicit; unknown fatality remains conservative.

`TIMEOUT`
- running provider command exceeded its finite monotonic execution deadline.
- worker generation is invalidated and hard-killed.

`WORKER_EXITED`
- worker process exited before a RUNNING command produced an accepted terminal result.
- provider outcome is indeterminate.

`PROTOCOL_ERROR`
- command terminal evidence could not be trusted due to a worker-protocol violation.
- whether the error invalidates the whole generation is governed by protocol severity below; command itself fails closed.

`CANCELLED_SHUTDOWN`
- command had not produced a terminal provider result and was cancelled by bounded supervisor shutdown policy.

`CANCELLED_GENERATION_INVALIDATED`
- queued/not-running command was cancelled because the provider worker generation was invalidated and executor-owned replay is forbidden.

### 7.2 `succeeded: bool` compatibility

The existing `ProviderCommandResult.succeeded: bool` is insufficient as the future supervisor's authoritative terminal vocabulary.

Do not overload it with:

- timeout;
- worker exit;
- protocol error;
- shutdown cancellation;
- generation cancellation.

Candidate integration rule:

> Introduce a separate resolved execution envelope/result type at the supervisor boundary. Preserve `ProviderCommandResult` only as the provider-call return normalization object if useful; do not force infrastructure-terminal states into its boolean.

No production schema change is made by this document.

## 8. First-terminal-wins

For each `command_id`, parent-owned terminal state is write-once.

Race rules:

1. valid result wins before timeout transition:
   - result terminal state is committed;
   - timeout check sees terminal and no-ops.

2. timeout wins first:
   - `TIMEOUT` is committed exactly once;
   - worker generation is invalidated;
   - any later result from that command/generation has diagnostic-only authority at most.

3. worker exit wins while command unresolved:
   - `WORKER_EXITED` is committed;
   - no provider success/failure is inferred.

4. shutdown cancellation wins before command dispatch:
   - `CANCELLED_SHUTDOWN` is committed;
   - command is never sent to child.

An impossible duplicate terminal result is a protocol/invariant finding; it never overwrites the first terminal truth.

## 9. Timeout policy contract

Every `ProviderCommandType` must resolve to a finite positive execution deadline before production use.

Current command types:

- CONNECT
- SUBSCRIBE
- UNSUBSCRIBE
- CLOSE
- QUERY_SUBSCRIPTION
- DIAGNOSTIC

V0.1 does **not** invent numeric timeout values in this design document.

Requirements:

- no command type may silently fall back to infinity;
- no unknown future command type may inherit an arbitrary default without explicit policy;
- startup has its own independent finite deadline;
- queue wait is measured separately from execution deadline;
- timeout decisions use parent monotonic time;
- UTC created/completed timestamps remain audit evidence;
- shutdown has a separate bounded graceful-close/kill budget.

Missing timeout policy for a command type is configuration/integration failure, not permission to run unbounded.

## 10. Worker startup contract

`Process.start()` does not mean worker runtime readiness.

Startup sequence:

```text
parent allocates generation-local IPC
parent spawns generation N
child imports provider adapter/SDK
child creates provider context
child installs callback handlers and outbound sender
child emits WORKER_RUNTIME_READY
parent validates envelope identity/generation/protocol
parent transitions STARTING -> IDLE
```

Parent starts a monotonic `startup_deadline` when generation spawn begins.

If runtime-ready is not validly accepted before deadline:

- classify generation `STARTUP_TIMEOUT` as worker lifecycle evidence;
- invalidate the generation;
- hard terminate/kill using the same bounded death-confirmation policy;
- discard generation-local IPC;
- do not issue provider commands to that generation.

`WORKER_RUNTIME_READY` proves only that the isolated runtime has initialized enough to accept commands. It does **not** prove:

- provider transport currentness;
- provider authentication/entitlement;
- desired subscription reconciliation;
- push flow;
- Currentness;
- Continuity;
- LIVE.

An explicit child `WORKER_INIT_FAILED` envelope may accelerate failure before the deadline; absence of such an envelope never converts timeout into success.

## 11. IPC topology

V0.1 candidate substrate: stdlib specialized supervisor using explicit Windows-compatible spawn semantics.

```text
multiprocessing.get_context("spawn")

parent-local bounded queue
        |
        v
parent supervisor -- command Pipe --> child worker
parent supervisor <-- event/result Pipe -- child sender thread
```

Requirements:

- two generation-local unidirectional IPC channels;
- one writer per IPC endpoint;
- replacement generation gets new channels;
- killed/dead generation channels are discarded and never reused;
- no provider SDK object crosses IPC;
- no correctness dependency on inheriting fork state;
- no shared cross-generation `multiprocessing.Queue`;
- no protocol-required cross-process Lock/Semaphore that could remain poisoned after hard termination.

Candidate building blocks:

- `multiprocessing.get_context("spawn")`
- `Process`
- generation-local `Pipe(duplex=False)` / `Connection`
- `send_bytes` / `recv_bytes`
- parent/child local `queue.Queue`/deque only inside one process
- process sentinel / bounded join
- monotonic watchdog

This is a candidate, not implementation freeze.

## 12. Wire envelope contract candidate

### 12.1 Transport representation

Candidate V0.1 representation:

- explicit UTF-8 JSON bytes;
- no arbitrary provider-object pickle payloads;
- explicit `protocol_version`;
- finite configurable maximum frame size;
- schema validation before an envelope gains execution authority.

The exact finite `max_frame_bytes` value remains implementation/config evidence work. Unlimited frame size is forbidden.

### 12.2 Child -> parent base fields

Every child-origin envelope must include:

- `protocol_version`
- `envelope_type`
- `runtime_instance_id`
- `provider_id`
- `worker_generation`
- `worker_event_seq`
- `observed_at_utc`
- type-specific normalized payload

Candidate envelope types:

- `WORKER_RUNTIME_READY`
- `WORKER_INIT_FAILED`
- `PROVIDER_EVENT`
- `COMMAND_TERMINAL`
- `OUTBOUND_LOSS`
- `WORKER_DIAGNOSTIC`

No generic heartbeat is added merely because process supervisors often have one. Add one only when an owned liveness invariant requires it.

### 12.3 Command terminal envelope

`COMMAND_TERMINAL` must correlate:

- `command_id`
- provider-call normalization status/payload/error evidence

The child does not get authority to redefine controller generation, desired revision, stream epoch, or semantic key from arbitrary response fields.

Parent resolves `command_id` against its immutable in-flight `ProviderCommand` and produces the resolved execution envelope.

### 12.4 Parent -> child command frame

Must include:

- protocol version;
- expected worker generation;
- serialized immutable `ProviderCommand` fields required by adapter execution;
- no provider objects or mutable caller references.

The child rejects wrong worker generation rather than trying to reinterpret it.

## 13. Child outbound concurrency/backpressure

Provider SDK callbacks may occur on SDK-owned threads.

They must not concurrently write the child->parent IPC endpoint.

Candidate child outbound architecture:

```text
SDK callback threads -> bounded child-local DATA queue
command/runtime path -> bounded child-local PRIORITY queue
                                  |
                                  v
                        one IPC sender thread
                                  |
                                  v
                         child->parent Pipe
```

Both lanes share a child-local monotonic `worker_event_seq` assignment rule before emission so loss/order evidence is auditable.

### 13.1 DATA overflow

Data-lane overflow may reject/drop market-data evidence only under explicit policy and must generate loss evidence.

Later Continuity logic must treat proven loss as relevant integrity evidence; the executor cannot silently preserve a continuity claim across known drops.

### 13.2 PRIORITY overflow

Required command-terminal/lifecycle/control evidence may not be silently dropped.

Candidate conservative rule:

> PRIORITY outbound overflow is worker-protocol failure and invalidates the worker generation.

The parent watchdog/process-liveness path remains the independent fail-closed mechanism if the child cannot communicate the failure itself.

Exact capacities remain configuration-owned and require implementation evidence. Unbounded queues are forbidden.

## 14. Protocol integrity policy

Protocol findings include:

- unsupported protocol version;
- malformed UTF-8/JSON/schema;
- unknown envelope type;
- wrong runtime identity;
- wrong provider identity;
- wrong worker generation;
- invalid/duplicate worker event sequence under the final sequence contract;
- terminal result for unknown command;
- impossible duplicate terminal result;
- oversized frame;
- structurally impossible lifecycle envelope.

Candidate severity split:

### `FRAME_REJECT`
A single malformed non-identity diagnostic/provider-data frame may be rejected only when the supervisor can prove rejecting it does not leave command/lifecycle terminal truth ambiguous.

### `GENERATION_FATAL`
Default for:

- runtime/provider/worker identity mismatch;
- malformed or unknown command terminal envelope;
- duplicate/impossible command terminal evidence;
- priority-channel integrity failure;
- protocol-version incompatibility;
- any protocol error that makes current worker execution authority ambiguous.

`GENERATION_FATAL` invalidates the worker generation and enters the normal kill/death path.

If severity cannot be proven safely, fail closed as `GENERATION_FATAL`.

## 15. Hard timeout / kill sequence

When a RUNNING command exceeds its execution deadline:

1. atomically commit terminal `TIMEOUT` if command is still unresolved;
2. immediately mark current worker generation invalid;
3. stop dispatching new commands;
4. cancel queued commands as `CANCELLED_GENERATION_INVALIDATED` under V0.1 candidate policy;
5. record execution-timeout evidence;
6. discard/close generation IPC from future authority;
7. request OS process termination;
8. bounded join;
9. if still alive and platform API distinguishes stronger kill, issue kill;
10. bounded final join;
11. confirm worker is no longer alive;
12. close dead process/IPC handles;
13. transition supervisor to `DEAD`;
14. only explicit higher recovery policy may request replacement generation.

If process death cannot be confirmed:

- transition supervisor to `FATAL`;
- do not spawn another provider worker beside the unresolved old process;
- surface intervention-required execution failure.

No infinite process-restart loop exists inside this execution layer.

## 16. Unexpected worker exit

If the current worker exits without an accepted terminal result:

- mark current generation invalid;
- RUNNING command -> `WORKER_EXITED`;
- queued commands -> `CANCELLED_GENERATION_INVALIDATED` under V0.1 policy;
- discard generation IPC;
- expose exit diagnostics if safely available;
- transition supervisor to `DEAD` unless killability/invariant evidence requires `FATAL`.

Do not infer whether the provider call itself succeeded immediately before the crash.

The controller/recovery layer decides whether and when a replacement generation is appropriate.

## 17. Shutdown contract

Shutdown is explicit and idempotent.

Candidate sequence:

1. transition supervisor to `STOPPING`;
2. reject new submit work;
3. terminally cancel never-dispatched queued commands as `CANCELLED_SHUTDOWN`;
4. if worker is idle, request bounded graceful worker shutdown/provider close;
5. if worker is executing, do not wait unbounded for that SDK call;
6. enforce shutdown grace deadline;
7. if worker has not exited, terminate/kill with bounded confirmation;
8. discard generation IPC;
9. transition to `DEAD` when process death is confirmed;
10. repeated shutdown performs no unsafe duplicate action.

A hung provider CLOSE is handled by the same process-kill boundary; CLOSE is not granted an unbounded exception to the timeout rule.

Post-stop old-worker evidence can never resurrect LiveFeed lifecycle. Existing frozen Case 20 remains authoritative.

## 18. Worker invalidation vs controller recovery

Freeze candidate:

> Worker invalidation does **not** mechanically increment or redefine the frozen controller/connection generation.

The supervisor emits execution/infrastructure evidence:

- timeout;
- worker exit;
- startup failure;
- protocol fatality;
- replacement-worker identity.

The authoritative controller/recovery design decides if that evidence causes a lifecycle/recovery transition and when its own connection/recovery generation changes.

This preserves frozen principle 10 rather than inserting a hidden extra connection-generation owner inside LANE 3.

## 19. JSON/codec performance boundary

V0.1 may implement/test the semantic envelope with normalized JSON bytes first.

Design freeze does not require proving JSON is forever the optimal codec.

Promotion requirement before Shadow/CORE:

- benchmark encoded recorded provider fixtures at expected peak event rates;
- measure frame-size distribution and CPU/latency overhead;
- prove bounded queues do not silently lose priority evidence;
- if JSON is insufficient, change codec beneath the same semantic envelope contract rather than weakening identity/protocol semantics.

Correctness and auditable schema precede codec optimization.

## 20. Windows/process semantics

Production design must use explicit `spawn` semantics and be tested as such.

Requirements:

- child target is module-level/importable;
- provider configuration is serializable;
- provider context is constructed only inside child;
- no correctness dependency on POSIX signals/fork inheritance;
- every `Process`/`Connection` handle is closed on teardown;
- hard-kill/orphan tests run on Windows CI before Windows production promotion;
- Linux CI runs the same semantic suite where applicable.

Provider worker V0.1 must not intentionally launch subprocess descendants. Killing the worker PID is not claimed to kill arbitrary descendants.

## 21. Required adversarial acceptance suite

Before implementation can move beyond ADAPTED, the exact implementation must prove at least:

1. normal startup reaches `IDLE` only after valid runtime-ready envelope;
2. startup that never returns is killed within parent-owned bound;
3. normal command produces exactly one terminal result;
4. provider rejection stays administrative rejection, not LIVE inference;
5. command that never returns -> TIMEOUT -> worker PID confirmed dead;
6. timeout/result race obeys first-terminal-wins;
7. unexpected worker crash mid-command -> WORKER_EXITED, never guessed provider result;
8. generation N result rejected after generation N+1 exists;
9. generation N IPC never reused by N+1;
10. parent local command queue is bounded and explicit on overflow;
11. queued commands are not auto-replayed after worker invalidation;
12. priority outbound overflow invalidates generation/fails closed;
13. data outbound overflow produces explicit loss evidence;
14. malformed command-terminal frame is generation-fatal;
15. wrong runtime/provider/worker identity is generation-fatal;
16. oversized frame is rejected/fails closed according to contract;
17. shutdown while idle is bounded/idempotent;
18. shutdown during normal command is bounded;
19. shutdown during a deliberately hung command kills worker and returns;
20. hung CLOSE cannot hang supervisor shutdown;
21. worker restart never produces LIVE or Currentness/Continuity by itself;
22. wall-clock jump fixture does not alter monotonic execution deadline;
23. child provider object is never required/pickled into parent test process;
24. provider callback threads cannot concurrently write outbound Pipe;
25. worker kill leaves no worker child PID alive after teardown;
26. failed kill confirmation enters FATAL and blocks replacement spawn;
27. supervisor allows at most one RUNNING provider RPC per generation;
28. a stale queued command is cancelled rather than silently replayed into a replacement worker.

### Windows acceptance

The killability subset must execute on at least one Windows CI runner before Windows production promotion:

- spawn startup;
- unreturning child command;
- timeout;
- worker PID death confirmation;
- replacement generation startup in a separate test after clean death;
- idempotent teardown;
- no orphan worker PID.

## 22. External dependency decision

### `ProcessPoolExecutor`

Reject as direct strict-timeout executor on the current Python 3.11 baseline. A caller wait timeout does not kill an already-running provider call.

### Pebble

Retain as `ADAPT / TEST-REUSE` method reference for per-task timeout -> worker termination -> replacement.

Do not add dependency yet: Radar still owns the hard parts — one long-lived provider context, callbacks, worker generation, IPC schema, command authority, and controller recovery separation.

### Loky

Retain as lifecycle/spawn/broken-worker reference. Its worker idle-timeout semantics do not directly satisfy per-running-command hard deadline.

### V0.1 preferred substrate candidate

`stdlib specialized single-provider supervisor` using `spawn + Process + generation-local Pipes + parent/child local queues + monotonic watchdog`.

This preference remains a candidate until implementation complexity is compared against Pebble after the contract is stable.

## 23. Remaining items before DESIGN:FROZEN

This candidate resolves most R1 blockers but does **not** freeze numeric/config choices or provider-specific behavior.

Remaining freeze gates:

1. exact resolved execution-envelope dataclass/schema and serialization field types;
2. exact parent supervisor transition table under concurrent submit/shutdown/result/timeout races;
3. exact timeout configuration source and validation contract for every `ProviderCommandType`;
4. exact max-frame and child/parent queue capacity configuration ownership (values require evidence, but fail-closed semantics can freeze first);
5. provider-adapter exception taxonomy: which returned exceptions leave a worker generation reusable vs generation-fatal;
6. integration seam by which supervisor execution evidence reaches the existing single writer without creating a second authoritative writer;
7. provider-source audit confirming the chosen Futu adapter path does not intentionally spawn descendant processes;
8. implementation proof that JSON normalization/throughput is adequate or codec replacement is needed;
9. Windows CI workflow design for hard-kill/orphan tests.

No production worker/adaptor implementation should start until items 1–7 are resolved and the resulting contract receives adversarial review. Items 8–9 may remain validation/promotion gates if their semantic constraints are already frozen.

## 24. Promotion rule

This design candidate may advance to `DESIGN:FROZEN` only if:

- it remains compatible with the authoritative Live Feed Reliability frozen contract;
- no executor state can self-promote controller lifecycle/LIVE truth;
- hard timeout kills the execution capability rather than merely returning early;
- identities remain orthogonal;
- every ambiguous terminal/race condition fails closed;
- Windows spawn/kill semantics are represented in the acceptance suite;
- no external library is promoted merely to reduce code volume without reducing the real session/identity risk.

Implementation then follows the ordinary Harvest path:

`DESIGN:FROZEN -> ADAPTED implementation -> VALIDATING -> SHADOW -> CORE`

## Governing sentence

> The provider worker may own execution; it may never own market truth.
