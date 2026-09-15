# LiveFeed Provider Worker — Slice A Implementation Brief V0.1

Status: **IMPLEMENTATION TASK — CONTRACTS/CONFIG ONLY**
Parent design: `LIVE_FEED_PROVIDER_WORKER_DESIGN_FREEZE_V0_1.md`

## 1. Goal

Translate the frozen Provider Worker execution contract into machine-enforced Python types and tests **without implementing multiprocessing, provider runtime behavior, Futu integration, or controller lifecycle changes**.

This is intentionally the smallest implementation slice after design freeze.

## 2. Allowed files

Preferred new files:

- `src/services/live_feed/provider_worker_contracts.py`
- `tests/test_live_feed_provider_worker_contracts.py`

Allowed supporting edits only when required:

- `src/services/live_feed/__init__.py` for explicit public exports;
- `.github/workflows/research-radar-tests.yml` to ensure the new test file actually runs;
- `.github/requirements-ci.txt` only if a test-only dependency is strictly required (expected: **none**).

Do not edit provider adapters or realtime monitor in Slice A.

## 3. Required public enums

Implement exactly:

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

```python
class ProviderExceptionDisposition(str, Enum):
    WORKER_REUSABLE = "WORKER_REUSABLE"
    GENERATION_FATAL = "GENERATION_FATAL"
```

No aliases and no extra members.

## 4. Required immutable domain types

Implement frozen dataclasses with **exact field order**:

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

## 5. Validation behavior

### 5.1 Common identities

Reject with `ValueError`:

- blank runtime/provider id;
- `worker_generation < 1`;
- negative monotonic timestamp;
- naive datetime;
- datetime with unusable `utcoffset()`;
- caller-supplied non-`None` `local_enqueue_seq` at construction for producer-origin evidence if the constructor contract chooses to enforce pre-ingress shape directly.

If existing repository convention requires allowing stamped reconstruction via `dataclasses.replace`, use a private/public constructor helper split or a narrow validation rule that permits only positive stamped sequence values. Do not silently accept arbitrary negative/zero sequence values.

### 5.2 `ResolvedProviderCommandOutcome`

Enforce:

- `command` is `ProviderCommand`;
- command runtime/provider identities equal envelope identities;
- `outcome` is a real `ProviderExecutionOutcome`, not a raw string;
- dispatched monotonic timestamp is required for `SUCCEEDED`, `PROVIDER_REJECTED`, `PROVIDER_EXCEPTION`, `TIMEOUT`, `WORKER_EXITED`, `PROTOCOL_ERROR`;
- dispatched timestamp may be `None` only for never-dispatched cancellation outcomes;
- if dispatched is present, terminal observed monotonic >= dispatched;
- terminal UTC datetime is aware and canonicalizable;
- normalized provider payload is frozen using the existing `freeze_normalized_payload` contract or an exactly equivalent existing repository primitive; no mutable caller mapping survives by reference.

Do **not** infer provider semantics from error text.

### 5.3 `ProviderWorkerLifecycleEvidence`

Enforce:

- `kind` is the exact enum type;
- PID when present is positive integer;
- exit code is diagnostic and may be negative/zero/positive according to platform semantics;
- UTC/monotonic/identity rules above.

### 5.4 `ProviderWorkerSupervisorConfig`

Enforce:

- all timeout values finite and > 0;
- every capacity/max frame integer > 0 and booleans rejected as integers;
- `protocol_version` integer >= 1, bool rejected;
- timeout mapping keys are exact `ProviderCommandType` enum instances;
- timeout mapping contains exactly every current `ProviderCommandType` member;
- missing member rejects;
- extra/foreign/raw-string key rejects;
- every command timeout finite and > 0;
- store timeout mapping immutably/read-only so caller mutation cannot change config after construction.

No default timeout/capacity values inside this domain type.

## 6. Payload immutability

Reuse `data_provider.live_feed_types.freeze_normalized_payload` where appropriate rather than inventing a second freezer.

Permanent test:

- construct outcome with nested mutable dict/list payload;
- mutate caller aliases afterward;
- stored outcome evidence remains unchanged/read-only.

Unsupported provider-native mutable objects follow the existing `OpaqueUnsupportedPayload` semantics rather than being retained by reference.

## 7. Required mechanical contract tests

Add anti-shrink tests asserting exact:

- enum member names/order/values for all three enums;
- dataclass field names/order for all three dataclasses;
- public export set chosen for this module;
- `ProviderCommandType` timeout coverage cannot shrink or grow without config test failure;
- dataclasses are frozen;
- raw valid-looking enum strings are rejected rather than coerced;
- bool is rejected for integer capacities/generation/protocol fields;
- NaN/+Inf/-Inf timeout values reject;
- naive datetime rejects;
- identity mismatch between outcome and embedded command rejects;
- impossible cancellation/dispatch combinations reject;
- mutable payload aliases cannot mutate stored evidence.

## 8. Negative architecture tests

Mechanically assert `provider_worker_contracts.py` does **not** import:

- `multiprocessing`;
- `futu`;
- realtime monitor packages;
- controller implementation module for mutation access;
- strategy/trading modules.

It may import:

- stdlib domain helpers;
- `ProviderCommand` / `ProviderCommandType`;
- `freeze_normalized_payload`.

No network, subprocess, thread, queue, file I/O, database or provider SDK behavior belongs in Slice A.

## 9. CI requirement

The new test file must be both:

1. covered by workflow path triggers; and
2. explicitly executed by the current focused Research Radar pytest command if that workflow still enumerates test files manually.

A green workflow that did not execute the new contract test is a failure of this task.

## 10. Definition of Done

Slice A is complete only when:

- exact frozen types are implemented;
- all validation invariants above are enforced;
- payload immutability is proven;
- mechanical anti-shrink tests exist;
- negative architecture tests prove no process/provider behavior leaked into the slice;
- focused test suite passes;
- repository CI passes on the exact head;
- diff contains no multiprocessing/Futu/runtime implementation;
- code review finds no second identity source or permissive fallback.

## 11. Explicit non-goals

Do not implement:

- `ProviderWorkerSupervisor`;
- worker process target;
- IPC codec/framing;
- watchers/coordinator;
- process start/terminate/kill;
- Futu adapter;
- execution-evidence controller ingress;
- controller lifecycle/recovery mappings;
- numeric production timeout values;
- Windows hard-kill tests.

Those belong to later slices after this contract layer passes review.

## 12. Recommended implementation order

1. enums;
2. common validation helpers kept private and narrow;
3. frozen config dataclass;
4. worker lifecycle evidence dataclass;
5. resolved command outcome dataclass;
6. payload freezing;
7. exact-shape tests;
8. adversarial validation tests;
9. AST/import boundary tests;
10. public exports;
11. CI enumeration update;
12. full diff/contract review.

## Governing instruction to implementer

> Implement the contract exactly. Do not improve the architecture, add convenience defaults, or begin Slice B early.