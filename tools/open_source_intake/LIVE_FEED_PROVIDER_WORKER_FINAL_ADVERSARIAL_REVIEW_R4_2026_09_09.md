# LiveFeed Provider Worker Supervisor — Final Adversarial Review R4

Status: **FINAL DESIGN REVIEW — PASS WITH RESOLUTIONS / NON-PRODUCTION**

Reviewed artifacts:

- authoritative Live Feed Reliability frozen contract;
- Provider Worker Supervisor Contract Candidate V0.1;
- Process-Isolated Supervisor Adversarial Review R1;
- Integration / Concurrency Review R2;
- Contract Shape R3;
- current Slice-1 controller/command boundary;
- Futu provider semantic/source evidence.

## 1. R4 conclusion

R4 found five implementation-level ambiguity traps not fully nailed by R3. All five can be resolved without changing the governing architecture:

1. supervisor ingress saturation must fail closed without granting mutation authority to watcher/caller threads;
2. provider callback ordering must not depend on multiple callback threads racing a shared sequence counter;
3. shutdown/submit admission must be deterministic without requiring caller threads to mutate supervisor lifecycle;
4. controller-generation binding on provider callbacks must not be opportunistically rebound across recovery;
5. child priority evidence must not be starved behind market-data backlog.

With the resolutions below, no remaining architecture contradiction was found. Numeric capacities/timeouts and provider-specific empirical tuning remain implementation/configuration evidence, not design blockers.

---

## 2. Finding R4-F1 — Supervisor inbox saturation

### Problem

R2/R3 require one parent coordinator to own mutable supervisor state, but child watcher and public callers still need to report events/intents. If the bounded supervisor observation inbox is full, the watcher cannot simply:

- drop process-exit/terminal/protocol evidence;
- block forever;
- mutate supervisor state itself.

Any of those would violate a core invariant.

### Resolution

Freeze an **out-of-band producer fault latch** that carries no market/execution state and grants no terminal authority.

Candidate semantics:

- normal producer observations use bounded nonblocking ingress;
- if a watcher/control producer cannot enqueue required priority evidence, it sets a thread-safe one-way `supervisor_integrity_fault` latch/event;
- the coordinator checks that latch before/after every timed wait and before dispatch;
- once observed, the coordinator alone commits `GENERATION_FATAL` handling:
  - stop dispatch;
  - invalidate current worker generation;
  - terminalize unresolved work conservatively;
  - kill/death-confirm current worker;
  - enter `DEAD` or `FATAL` according to killability result.

Setting the latch is evidence production, not authoritative mutation.

The latch never resets within the affected worker generation.

If the supervisor process/coordinator itself is not scheduling, no in-process mechanism can manufacture safety; external service/process supervision remains a deployment concern.

---

## 3. Finding R4-F2 — `worker_event_seq` producer race

### Problem

Futu/provider callbacks may occur on multiple SDK threads. Assigning a shared `worker_event_seq` on callback producer threads creates another synchronization/ordering authority and can make sequence order a thread scheduling accident.

### Resolution

Freeze:

> Only the single child IPC sender thread assigns `worker_event_seq`, immediately before serialization/transmission.

Consequences:

- callback/runtime/command producer threads enqueue immutable child-local evidence without wire sequence authority;
- sender chooses the next outbound item under priority policy;
- sender assigns the next strictly monotonic sequence;
- sequence means **wire emission order for transmitted frames**, not provider source-time order;
- dropped DATA evidence does not consume a wire sequence; loss is represented by explicit `OUTBOUND_LOSS` count/range evidence;
- duplicate/regressing wire sequence from one generation is protocol-fatal at parent.

No provider sequence semantics are inferred from `worker_event_seq`.

---

## 4. Finding R4-F3 — Submit vs shutdown admission

### Problem

If every submit/shutdown action goes through one bounded inbox, command submissions can head-of-line block process-exit/terminal/shutdown evidence. If caller threads directly mutate supervisor state to close submission, single-coordinator ownership is weakened.

### Resolution

Freeze two concepts:

### 4.1 Producer-facing submission transport

- `ProviderCommandExecutor.submit()` writes only to a dedicated bounded **command-ingress transport queue**;
- this queue is not authoritative supervisor state;
- `put_nowait` failure is explicit `CommandQueueFull` / equivalent admission failure;
- accepted ingress does not imply provider execution success.

### 4.2 Submission admission gate

A narrow thread-safe producer-facing admission latch exists only to answer:

> May new submit requests still enter transport?

Shutdown atomically closes this admission latch before publishing shutdown intent.

This latch is not supervisor lifecycle state and cannot reopen automatically.

Semantics:

- submit that passes the admission latch and `put_nowait` before closure is admitted to local transport;
- submit after closure is rejected immediately;
- coordinator owns all subsequent command state/terminal cancellation;
- any admitted but undispatched command found during shutdown becomes `CANCELLED_SHUTDOWN`;
- no producer thread marks terminal outcomes.

### 4.3 Priority supervisor observation lane

Child terminal/process/protocol observations and shutdown intent use a separate bounded priority ingress/latch path so a flood of command submissions cannot prevent lifecycle evidence from being observed.

The coordinator is still the only state mutation owner.

---

## 5. Finding R4-F4 — Controller generation callback rebinding

### Problem

R2 correctly forbids stamping a child callback with `controller.snapshot().controller_generation` at receipt time. A subtler loophole remains if a long-lived worker is simply "rebound" in place to a newer controller generation while old SDK callback threads/buffers may still exist.

That could launder old provider evidence into a new controller generation.

### Resolution — V0.1 no in-place rebind

Freeze for Provider Worker V0.1:

> One worker generation has one immutable `controller_generation_binding` for provider callback normalization. It cannot be changed in place.

Worker-generation startup metadata therefore binds at minimum:

```text
runtime_instance_id
provider_id
worker_generation
controller_generation_binding
```

Provider callbacks emitted by that worker are converted using that immutable binding.

If the authoritative controller/recovery design creates a new controller/connection generation and future callbacks must carry that new identity:

- the old worker generation is invalidated for callback authority;
- V0.1 does not mutate its binding;
- a fresh worker generation/session is required for provider evidence under the new binding.

Important asymmetry:

```text
controller generation change -> may require fresh worker generation for new callback authority
worker generation change      -X-> does NOT automatically change controller generation
```

This preserves identity orthogonality while providing a hard anti-laundering boundary.

Executor/recovery integration may later design a stronger provider-attested rebinding barrier, but V0.1 may not infer one.

---

## 6. Finding R4-F5 — Priority starvation behind DATA

### Problem

A single child sender servicing DATA and command/lifecycle evidence fairly/FIFO can delay a command terminal result behind a market-data burst. That could convert an on-time provider return into a parent-observed timeout or delay fatal lifecycle evidence.

### Resolution

Freeze strict outbound priority:

1. PRIORITY lane is always checked/drained before DATA lane;
2. command terminal, worker lifecycle, protocol and `OUTBOUND_LOSS` evidence are PRIORITY;
3. ordinary provider market-data callbacks are DATA;
4. DATA starvation under sustained priority load is acceptable compared with losing terminal/lifecycle truth and is itself observable through queue/continuity health;
5. PRIORITY overflow is generation-fatal;
6. DATA overflow is explicit loss evidence;
7. one sender thread remains the only Pipe writer and wire-sequence allocator.

This priority rule is an execution-integrity rule, not a market-data preference policy.

---

## 7. Additional adversarial checks

### R4-A1 — early result but blocked watcher

A provider command returns before deadline, but complete terminal frame cannot be received by parent before deadline because the pipe/watcher path is blocked.

Result: TIMEOUT is allowed and conservative. Deadline authority is based on **complete parent observation**, not unverifiable child-local completion time.

Do not accept child-reported completion timestamps as deadline authority.

### R4-A2 — child lies about command identity

Child terminal frame contains an unknown command id or a command id not dispatched to its worker generation.

Result: protocol/generation fatal. Parent immutable in-flight table is authority.

### R4-A3 — duplicate command id submitted

Supervisor admission/coordinator must reject a `command_id` that conflicts with an existing queued/running/terminal identity retention window according to implementation policy. A duplicate id cannot create two terminal truths.

Implementation must define bounded terminal-id retention adequate to prevent immediate duplicate reuse; command IDs are expected to be unique by construction.

### R4-A4 — result after command cancellation

A never-dispatched command cannot legitimately receive a provider terminal result. Such a frame is protocol-fatal/unknown-command evidence.

A dispatched RUNNING command cancelled by shutdown follows first-terminal-wins; late provider result cannot overwrite cancellation/timeout.

### R4-A5 — worker ready after startup timeout

If startup timeout has committed, a late `WORKER_RUNTIME_READY` from that generation is stale/diagnostic only and generation remains invalidated/killed.

### R4-A6 — kill confirmation races process exit

Process may exit naturally between terminate request and kill check. Death confirmation, not which OS action caused it, is authoritative. Do not misclassify a confirmed-dead worker as kill failure merely because a later kill syscall finds no live process.

### R4-A7 — PID reuse

PID is never execution identity. `worker_generation` + owned `Process` handle is authority. A reused OS PID cannot resurrect an old generation.

### R4-A8 — config enum growth

If a future `ProviderCommandType` is added and timeout mapping is not updated, supervisor config construction/startup must fail mechanically. No generic fallback.

### R4-A9 — oversized child DATA frame

Even DATA is untrusted protocol input. Oversized/malformed frame is not silently truncated. Because frame-boundary integrity is compromised for the generation-local channel, parent fails closed under protocol severity policy.

### R4-A10 — sender blocked while priority fills

If parent cannot drain child Pipe, sender may block and child PRIORITY queue may fill. PRIORITY overflow/fault plus parent-side integrity-fault/watchdog logic invalidates generation. No unbounded sender thread backlog.

---

## 8. Updated implementation topology

```text
CALLER THREADS
    |
    | nonblocking admission
    v
bounded command ingress --------------------+
                                             |
shutdown caller -> closes admission latch ---|----+
                                                  |
child watcher -> priority observation ingress ----|----> SupervisorCoordinator
child watcher -> integrity-fault latch -------------+       ONLY state writer
                                                            |
                                                            | one writer
                                                            v
                                                    parent command Pipe
                                                            |
                                                            v
                                           ProviderWorkerProcess generation N
                                           immutable controller-gen binding
                                               |                 |
                                  provider callback threads     command path
                                               |                 |
                                      bounded DATA queue   bounded PRIORITY queue
                                               \                 /
                                                \               /
                                                  sender thread
                                             strict PRIORITY first
                                             assigns worker_event_seq
                                                        |
                                                        v
                                               child event Pipe
                                                        |
                                                        v
                                                   child watcher
```

No edge in this topology allows supervisor/watcher/provider threads to mutate LiveFeed authoritative truth.

---

## 9. Final freeze invariants added by R4

PWS-21. Required supervisor priority-observation ingress loss is generation-fatal; producer threads may signal a one-way integrity-fault latch but may not mutate supervisor state.

PWS-22. Only the child IPC sender assigns `worker_event_seq`; it represents transmitted wire order only.

PWS-23. Public submit uses bounded producer transport and a narrow shutdown admission gate; terminal/supervisor state remains coordinator-owned.

PWS-24. One worker generation has one immutable `controller_generation_binding`; V0.1 forbids in-place callback rebinding across controller generations.

PWS-25. Child outbound sender gives strict priority to terminal/lifecycle/protocol/loss evidence over ordinary market-data DATA frames.

PWS-26. Parent complete-frame observation time, not child-reported provider completion time, is deadline authority.

PWS-27. PID is diagnostic only; worker generation + owned process handle define execution-process authority.

PWS-28. Future enum/config growth fails closed; missing timeout/capacity policy cannot inherit a permissive default.

---

## 10. Final implementation acceptance additions

Add to the permanent suite:

29. supervisor priority inbox saturation triggers integrity-fault latch -> coordinator generation fatal;
30. watcher/caller cannot invoke supervisor mutation helpers directly;
31. multiple callback threads cannot assign/write wire sequence concurrently;
32. strict PRIORITY-before-DATA terminal delivery under synthetic data flood;
33. submit after shutdown admission close is rejected without coordinator state mutation by caller;
34. submit admitted immediately before shutdown becomes coordinator-owned `CANCELLED_SHUTDOWN` if undispatched;
35. controller-generation binding is immutable for a worker generation;
36. old worker cannot be rebound and emit current-generation callbacks after controller generation change;
37. early child-local completion but late parent frame receipt times out conservatively;
38. late WORKER_RUNTIME_READY after startup timeout cannot revive generation;
39. PID reuse fixture/abstraction cannot substitute for worker generation identity;
40. adding a synthetic future command enum member without timeout mapping fails config validation.

---

## 11. Final verdict

R4 found no unresolved architecture-level blocker after applying the resolutions above.

Recommended status for the combined Provider Worker Supervisor execution contract:

> **DESIGN: FROZEN — implementation not started**

What remains is deliberately implementation/promotion evidence, not design invention:

- choose numeric timeout/capacity/frame limits from provider evidence and benchmark results;
- implement the frozen domain types/state machine/supervisor using a narrow stdlib-first slice;
- prove Linux pure-process acceptance suite;
- prove Windows spawn/hard-kill/orphan subset;
- run exact-version Futu source/process-tree audit;
- benchmark JSON envelope throughput;
- run controlled Futu Shadow fault validation using the existing localhost transport proxy;
- only then consider SHADOW/CORE promotion.

External library decision remains:

- Toxiproxy: not needed for current P0; reconsider for latency/jitter/half-open/asymmetric Currentness/Continuity fault work;
- Pebble: retain method reference, no dependency now;
- Loky: retain lifecycle reference, no dependency now;
- stdlib specialized single-provider supervisor remains preferred for V0.1 because Radar owns session identity, callbacks, global ingress, and recovery separation regardless of pool library.

## Governing sentence

> Killability without authority discipline is unsafe; authority discipline without killability is unreliable. Provider Worker V0.1 requires both.