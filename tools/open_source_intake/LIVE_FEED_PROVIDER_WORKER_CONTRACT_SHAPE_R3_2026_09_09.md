# LiveFeed Provider Worker Supervisor — Contract Shape R3

Status: **DESIGN REVIEW R3 — FREEZE CANDIDATE / NON-PRODUCTION**

This review resolves the six architecture blockers left by R2. It remains subordinate to the authoritative frozen `docs/LIVE_FEED_RELIABILITY_CONTRACT_V0_1.md` and cannot grant provider-worker execution facts authority over desired truth, controller generation, Currentness, Continuity, or LIVE.

## 1. R3 decision summary

R3 freezes as candidates:

1. exact execution-evidence enums and immutable domain shapes;
2. exact supervisor configuration completeness/validation semantics without inventing timeout numbers;
3. default-fatal provider exception classification;
4. writer authority matrix for every execution/lifecycle evidence class;
5. generation-local IPC capacity ownership and fail-closed rules;
6. cross-platform CI acceptance topology, including Windows hard-kill/orphan proof.

R3 does **not** implement the supervisor or provider adapter.

---

## 2. Exact terminal execution enum

Candidate public enum:

```python
class ProviderExecutionOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_EXCEPTION = "PROVIDER_EXCEPTION"
    TIMEOUT = "TIMEOUT"
    WORKER_EXITED = "WORKER_EXITED"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    CANCELLED_SHUTDOWN = "CANCELLED_SHUTDOWN"
    CANCELLED_GENERATION_INVALIDATED = "CANCELLED_GENERATION_INVALIDATED"
```

No `UNKNOWN_SUCCESS`, `PARTIAL_SUCCESS`, or boolean fallback exists.

`SUCCEEDED` remains administrative provider-call success only.

---

## 3. Exact worker lifecycle evidence enum

Candidate public enum:

```python
class ProviderWorkerEvidenceKind(str, Enum):
    WORKER_RUNTIME_STARTED = "WORKER_RUNTIME_STARTED"
    WORKER_RUNTIME_READY = "WORKER_RUNTIME_READY"
    WORKER_INIT_FAILED = "WORKER_INIT_FAILED"
    WORKER_STARTUP_TIMEOUT = "WORKER_STARTUP_TIMEOUT"
    WORKER_EXITED = "WORKER_EXITED"
    WORKER_TIMEOUT_KILLED = "WORKER_TIMEOUT_KILLED"
    WORKER_PROTOCOL_FATAL = "WORKER_PROTOCOL_FATAL"
    WORKER_KILL_FAILED = "WORKER_KILL_FAILED"
    WORKER_SHUTDOWN_COMPLETED = "WORKER_SHUTDOWN_COMPLETED"
```

These values describe executor infrastructure only. None is a `LifecycleState` alias.

---

## 4. Exact resolved command-outcome domain shape

Candidate immutable domain type:

```python
@dataclass(frozen=True)
class ResolvedProviderCommandOutcome:
    runtime_instance_id: str
    provider_id: str
    worker_generation: int
    command: ProviderCommand
    outcome: ProviderExecutionOutcome
    dispatched_at_monotonic_ns: int | None
    terminal_observed_at_monotonic_ns: int
    terminal_at_utc: datetime
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    normalized_provider_payload: Mapping[str, Any] | None = None
    diagnostic_reason: str | None = None
    local_enqueue_seq: int | None = None
```

### 4.1 Invariants

Construction/ingress validation must enforce:

- non-empty `runtime_instance_id` and `provider_id`;
- `worker_generation >= 1`;
- `terminal_observed_at_monotonic_ns >= 0`;
- `terminal_at_utc` is timezone-aware UTC-normalizable;
- `command.runtime_instance_id == runtime_instance_id`;
- `command.provider_id == provider_id`;
- `local_enqueue_seq is None` before controller ingress stamping;
- `dispatched_at_monotonic_ns is None` only for commands terminally cancelled before dispatch;
- if dispatch exists, `terminal_observed_at_monotonic_ns >= dispatched_at_monotonic_ns`;
- `normalized_provider_payload` is recursively frozen before authoritative writer consumption;
- provider error fields are evidence strings only; they do not define FailureClass by themselves.

### 4.2 Outcome-specific constraints

`SUCCEEDED` / `PROVIDER_REJECTED` / `PROVIDER_EXCEPTION`:
- must have `dispatched_at_monotonic_ns`;
- must correspond to a child/provider terminal observation accepted for the same immutable parent-issued command.

`TIMEOUT`:
- must have `dispatched_at_monotonic_ns`;
- terminal monotonic timestamp is the parent-owned deadline/timeout commitment time;
- no provider success/rejection payload is required or inferred.

`WORKER_EXITED`:
- command had been dispatched and was unresolved when current worker exit became authoritative.

`CANCELLED_SHUTDOWN` / `CANCELLED_GENERATION_INVALIDATED`:
- may have `dispatched_at_monotonic_ns is None` only for never-dispatched queued commands;
- V0.1 does not use these labels to overwrite an already RUNNING command's more specific terminal outcome.

`PROTOCOL_ERROR`:
- command identity is known but terminal provider evidence cannot be trusted;
- generation-fatal protocol policy applies unless a future frozen exception explicitly narrows it.

### 4.3 Why embed `ProviderCommand`

The immutable original command remains the single source for:

- controller generation;
- desired registry revision;
- stream subscription epoch;
- semantic stream key;
- command id/type;
- command created time.

R3 rejects flattening those fields into a second partially-authoritative execution schema.

---

## 5. Exact worker lifecycle evidence domain shape

Candidate immutable type:

```python
@dataclass(frozen=True)
class ProviderWorkerLifecycleEvidence:
    runtime_instance_id: str
    provider_id: str
    worker_generation: int
    kind: ProviderWorkerEvidenceKind
    observed_at_monotonic_ns: int
    observed_at_utc: datetime
    process_pid: int | None = None
    exit_code: int | None = None
    diagnostic_reason: str | None = None
    local_enqueue_seq: int | None = None
```

Invariants:

- non-empty runtime/provider identity;
- `worker_generation >= 1`;
- monotonic timestamp non-negative;
- aware UTC audit time;
- `local_enqueue_seq is None` before controller ingress stamping;
- PID/exit code are diagnostic execution facts, never provider/business identity;
- an old `worker_generation` may remain historical evidence but cannot acquire current execution authority after replacement.

---

## 6. Global controller ingress union

R3 freezes the future writer-facing conceptual union:

```text
LiveFeedIngressItem =
    ProviderEvent
    | ControllerIntent
    | ResolvedProviderCommandOutcome
    | ProviderWorkerLifecycleEvidence
```

Every accepted item that may influence authoritative controller/recovery interpretation receives one `local_enqueue_seq` from the **same controller-local monotonic allocator**.

Physical queues may remain separate for bounded backpressure, but writer application order is globally merged by that sequence.

Existing `_pending_command_results` cannot remain a second authoritative ordering domain once execution outcomes gain state semantics. Diagnostic history, if retained, is derived from writer-consumed outcomes.

---

## 7. Supervisor configuration contract

Candidate immutable config shape:

```python
@dataclass(frozen=True)
class ProviderWorkerSupervisorConfig:
    startup_timeout_seconds: float
    command_timeout_seconds: Mapping[ProviderCommandType, float]
    graceful_shutdown_timeout_seconds: float
    terminate_join_timeout_seconds: float
    kill_join_timeout_seconds: float
    parent_command_queue_capacity: int
    child_data_queue_capacity: int
    child_priority_queue_capacity: int
    supervisor_inbox_capacity: int
    max_frame_bytes: int
    protocol_version: int
```

### 7.1 Validation freezes

- every timeout is finite and strictly positive;
- every queue/frame capacity is finite integer and strictly positive;
- `protocol_version >= 1`;
- `command_timeout_seconds` contains **exactly** every current `ProviderCommandType` member;
- missing command type -> config construction/startup failure;
- unknown extra command type key -> config validation failure;
- no infinite/default timeout;
- no implicit capacity default inside production supervisor;
- config is immutable after supervisor construction;
- configuration source may be file/env/application composition, but the supervisor receives one fully materialized validated config object.

R3 intentionally does not choose numeric values. Provider evidence/benchmarking owns those values; contract completeness owns their existence.

### 7.2 Queue wait

V0.1 records queue wait but does not introduce a queue-age timeout in this contract. A future queue-age deadline requires a separate explicit policy; it must not be silently conflated with provider RPC execution timeout.

---

## 8. Provider exception fatality contract

R3 freezes **default-fatal** classification.

Candidate adapter-facing enum:

```python
class ProviderExceptionDisposition(str, Enum):
    WORKER_REUSABLE = "WORKER_REUSABLE"
    GENERATION_FATAL = "GENERATION_FATAL"
```

Rule:

> An exception is `GENERATION_FATAL` unless the provider adapter contains an explicit, tested classification proving the worker/session remains reusable for that exact exception family/context.

Consequences:

- unknown exception -> `PROVIDER_EXCEPTION` command terminal outcome + generation invalidation;
- explicit tested reusable exception -> `PROVIDER_EXCEPTION` outcome, supervisor may return `BUSY -> IDLE`;
- timeout is never downgraded to reusable exception;
- protocol errors are not provider exceptions and follow protocol fatality rules;
- provider rejection returned normally is not an exception and does not by itself invalidate generation.

No string matching on exception message may silently grant `WORKER_REUSABLE` authority. Classification must be typed/structured or otherwise adapter-explicit and regression-tested.

---

## 9. Writer authority matrix

The supervisor owns execution truth only. The LiveFeed writer owns interpretation.

| Evidence | Minimum writer authority | Forbidden interpretation |
|---|---|---|
| command `SUCCEEDED` | record current/stale administrative result; command-specific reconciliation may consume it if identity is current | subscription confirmed, Currentness, Continuity, LIVE |
| `PROVIDER_REJECTED` | record rejection; current command-specific control policy may mark/request failure under explicit provider semantics | automatic FAILED/LIVE inference unrelated to command policy |
| reusable `PROVIDER_EXCEPTION` | record execution failure evidence | provider business rejection; LIVE inference |
| fatal `PROVIDER_EXCEPTION` | record generation-invalidating execution evidence; recovery policy may downgrade/invalidate trust | supervisor directly changing controller generation/LIVE |
| `TIMEOUT` | record hard execution-boundary failure; recovery policy may degrade/reconnect/fail according to its own contract | guessing whether provider operation succeeded |
| `WORKER_EXITED` command outcome | record indeterminate execution result and infrastructure loss | provider success/rejection guess |
| `PROTOCOL_ERROR` | record untrusted command completion + fatal execution integrity evidence | accepting malformed payload as provider result |
| command cancellation | record cancellation; controller decides whether current desired intent requires reissue | executor auto-replay |
| `WORKER_RUNTIME_STARTED` | diagnostics/infrastructure observation only | provider connected/ready |
| `WORKER_RUNTIME_READY` | executor can accept commands | CONNECTED/LIVE/auth/subscription readiness |
| startup failure/timeout | infrastructure unavailable evidence | provider business failure guess |
| worker timeout-killed/exited | infrastructure/session invalidation evidence | automatic replacement means recovery |
| `WORKER_KILL_FAILED` | fail-closed intervention-required execution condition; block automatic replacement | spawning another worker beside unresolved old worker |
| shutdown completed | execution teardown fact | market/session lifecycle fact |

### 9.1 Upgrade/downgrade asymmetry

R3 freezes:

- worker evidence may justify **loss/invalidation of execution trust**;
- worker evidence alone may never upgrade market-data trust;
- any controller lifecycle downgrade remains a writer/recovery-policy action, not a supervisor mutation;
- no worker evidence can directly produce `LIVE`, `CURRENTNESS_PROVEN`, or `CONTINUITY_PROVEN`.

### 9.2 `WORKER_KILL_FAILED`

This is the one execution condition whose minimum safe interpretation is explicit:

- supervisor enters `FATAL`;
- automatic provider-worker replacement is forbidden;
- writer receives globally sequenced fatal infrastructure evidence;
- higher-level health/recovery policy must surface intervention-required/unavailable execution capability.

R3 does not require a specific `LifecycleState` transition for this evidence; that remains owned by the frozen/future controller recovery policy.

---

## 10. Supervisor coordinator transition contract under races

Only the coordinator mutates supervisor state.

### 10.1 Submit vs shutdown

The coordinator's observed inbox sequence decides acceptance:

- `SUBMIT_REQUEST` processed before committed `SHUTDOWN_REQUEST`: command may enter bounded local queue if other acceptance checks pass;
- `SHUTDOWN_REQUEST` once committed closes acceptance; later submit -> explicit rejection;
- queued-but-undispatched commands present at shutdown -> `CANCELLED_SHUTDOWN`.

No caller thread can race by mutating queue/terminal state directly.

### 10.2 Result vs timeout

Authority uses watcher-stamped complete-frame observation time, not coordinator dequeue time:

```text
terminal_frame_observed_ns < execution_deadline_ns -> eligible result
terminal_frame_observed_ns >= execution_deadline_ns -> TIMEOUT
```

A malformed frame never wins merely by being early.

### 10.3 Result vs process exit

If child event pipe and process sentinel are ready in one watcher cycle:

- drain complete available frames first;
- stamp them;
- then enqueue process-exit evidence;
- coordinator still validates identity/deadline/terminal state.

Partial frame/EOF without accepted terminal -> `WORKER_EXITED` for unresolved RUNNING command.

### 10.4 Shutdown vs RUNNING command

- shutdown stops new dispatch;
- RUNNING command is not granted unlimited completion time;
- shutdown grace deadline is parent-monotonic;
- if unresolved at grace expiry, generation is terminated/killed;
- terminal command result is `CANCELLED_SHUTDOWN` only when cancellation policy wins before a more specific terminal execution outcome; if a hard execution timeout already committed, `TIMEOUT` remains first-terminal truth.

### 10.5 Worker exit vs timeout

First authoritative observation under coordinator rules wins the command terminal classification, subject to deadline timestamps:

- process exit observed while command unresolved before timeout commitment -> `WORKER_EXITED`;
- timeout commitment already won -> `TIMEOUT`; later exit is worker lifecycle evidence only.

No second terminal overwrite.

---

## 11. IPC/frame capacity ownership

Numeric values are configuration-owned, semantics are frozen:

- parent command queue overflow -> submit rejects explicitly, no silent drop;
- supervisor inbox overflow -> execution-integrity failure; fail closed and invalidate current generation if an observation may have been lost;
- child DATA queue overflow -> explicit `OUTBOUND_LOSS` evidence; no silent continuity preservation;
- child PRIORITY queue overflow -> generation-fatal;
- child->parent frame exceeding `max_frame_bytes` -> protocol failure; command/lifecycle frames are generation-fatal;
- parent->child oversized command frame -> do not dispatch; explicit local protocol/config failure;
- no unbounded queue/frame path.

Capacity exhaustion is evidence, not an excuse to overwrite oldest priority truth.

---

## 12. Serialization contract boundary

R3 freezes semantic requirements, not forever-codec choice:

- V0.1 implementation starts with explicit UTF-8 JSON bytes;
- protocol version required;
- schema validation required;
- no arbitrary pickle/provider object transfer;
- unknown enum/envelope type fails closed;
- codec may later change only beneath the same domain/schema authority rules.

Performance benchmark is a Shadow/promotion gate, not a design blocker.

---

## 13. Futu exception/session rule

Until adapter-specific tests prove otherwise:

- any uncaught Futu SDK exception escaping a provider command handler is `GENERATION_FATAL`;
- ordinary explicit SDK `ret != RET_OK`/provider rejection returned as a normal response is normalized as `PROVIDER_REJECTED` and does not automatically kill the worker;
- timeout always kills generation;
- callback handler exception policy must prevent one malformed callback from silently killing the sender/control path; unhandled child-process-fatal callback failures are worker exit/protocol evidence, never silently ignored.

This is conservative by design.

---

## 14. Exact Futu descendant-process validation gate

R2 source audit found no normal long-lived provider subprocess ownership in inspected public paths, but this is version-sensitive.

Before Futu Shadow promotion:

1. record exact installed SDK version/build;
2. source-scan that exact installed package for `subprocess`, `multiprocessing`, `os.system`, process-launch helpers;
3. record process tree before child startup;
4. record process tree after Futu import/context init;
5. record during normal subscribe/query;
6. record during induced timeout/worker kill;
7. prove no unexpected descendant remains after worker death;
8. if descendants appear, block hard-killability claim and design explicit process-tree ownership before continuing.

This remains a validation gate, not an architecture blocker.

---

## 15. CI acceptance topology

### 15.1 Linux required on every implementation PR

Run pure provider-worker supervisor suite with **no Futu SDK requirement** using fake child targets:

- spawn startup/ready;
- startup hang timeout kill;
- normal terminal result;
- result/deadline races;
- worker crash;
- generation-local IPC replacement;
- queue overflow;
- malformed/oversized protocol frames;
- hung command killability;
- shutdown idle/busy/hung;
- no orphan child after teardown;
- wall-clock jump vs monotonic deadline;
- global LiveFeed ingress ordering adapter tests.

### 15.2 Windows required before Windows production promotion

A dedicated Windows job must execute the hard process subset using explicit `spawn`:

- importable module-level child target;
- worker startup readiness;
- startup hang kill;
- unreturning command -> hard deadline -> PID dead;
- post-death IPC disposal;
- fresh replacement generation in a **separate** test after confirmed cleanup;
- shutdown hung child;
- repeated teardown;
- no orphan PID/process handle.

A Linux-only green suite cannot promote Windows provider-worker isolation to production-ready.

### 15.3 Test isolation rules

- tests never kill external OpenD;
- pure killability tests use owned fake child processes only;
- PID identity must be the exact `multiprocessing.Process` child handle created by the test;
- cleanup in `finally`/fixture teardown;
- failure to clean a child is a test failure, not a warning;
- no machine-wide firewall/routing mutations.

### 15.4 Futu Shadow tests

Not normal CI. Controlled environment only after pure supervisor suite passes:

- worker owns real Futu context;
- existing localhost transport proxy may cut/restore only the test connection;
- parent remains responsive during provider outage;
- dangerous sync RPC cannot freeze parent/controller;
- timeout/kill affects only owned provider worker;
- provider auto-resubscribe never self-promotes LIVE;
- process-tree cleanup recorded.

---

## 16. Mechanical contract tests required with implementation

The implementation PR must add frozen-shape tests for:

- exact `ProviderExecutionOutcome` member set;
- exact `ProviderWorkerEvidenceKind` member set;
- exact `ProviderExceptionDisposition` member set;
- exact field names/order for both execution-evidence dataclasses;
- exact `ProviderWorkerSupervisorConfig` field names/order;
- exact current `ProviderCommandType` coverage in timeout config validation;
- no raw `succeeded: bool` substitution for infrastructure terminal outcomes;
- no `LifecycleState.LIVE` reference inside provider-worker supervisor module except negative invariant/docs if mechanically unavoidable;
- no provider SDK import in parent supervisor module;
- child provider target is importable/module-level for spawn;
- execution evidence ingress is producer-only and cannot invoke authoritative controller mutation helper directly.

---

## 17. R3 blocker resolution

R2 remaining blocker -> R3 outcome:

1. exact execution-evidence schema -> **RESOLVED** by Sections 2–5;
2. timeout configuration source/validation -> **RESOLVED AT CONTRACT LEVEL** by Section 7; numeric values remain config/evidence;
3. queue/frame ownership -> **RESOLVED AT CONTRACT LEVEL** by Sections 7 and 11; numeric values remain config/evidence;
4. provider exception taxonomy -> **RESOLVED CONSERVATIVELY** by Sections 8 and 13;
5. writer interpretation boundary -> **RESOLVED** by Section 9 and global ingress union;
6. Windows CI mechanics -> **RESOLVED AS PROMOTION CONTRACT** by Section 15.

JSON throughput and exact Futu process-tree behavior remain explicit validation/promotion gates, not architecture blockers.

---

## 18. R3 recommendation

The Provider Worker Supervisor design is now **eligible for final adversarial freeze review**.

Do not implement production provider code yet.

The final review should try to break at least:

- terminal outcome uniqueness;
- stale generation isolation;
- command cancellation/reissue authority;
- execution evidence global ordering;
- worker kill failure handling;
- callback anti-laundering across controller generations;
- child outbound priority/data backpressure;
- startup timeout and shutdown timeout symmetry;
- Windows spawn/import behavior;
- configuration completeness after future enum growth.

If no architecture-level contradiction remains, advance the combined Provider Worker contract to `DESIGN:FROZEN` and issue a narrow implementation task.

## Governing sentence

> Execution evidence may explain why trust was lost; it can never manufacture trust.