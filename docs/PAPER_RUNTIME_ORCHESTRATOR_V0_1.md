# PAPER_RUNTIME_ORCHESTRATOR_V0.1

Status: implementation candidate, paper-only, stacked on
`PAPER_EXECUTION_ADMISSION_V0.1`.

## Purpose

Provide the thin runtime lifecycle owner that was still missing after the
Execution Engine, Live Shadow, and deterministic paper-admission bridge were
built.

The runtime path is:

```text
explicit upstream permission + PaperOrderSpec
-> PaperRuntimeOrchestrator
-> admission bridge
-> Shadow preview (non-mutating)
-> existing RiskGuard
-> existing ExecutionEngine
-> factory-issued paper adapter
-> journal / order / fill truth
```

## Lifecycle

`NEW -> READY -> STOPPED`, with a fail-closed `FAILED` state.

`start()` must complete the existing Execution Engine reconciliation before
the runtime becomes READY. A reconciliation exception moves the runtime to
FAILED and it cannot be restarted in-place.

`process()` is accepted only while READY.

Unexpected non-domain exceptions during processing move the runtime to FAILED.
Expected `ExecutionBlocked` outcomes are fail-closed rejections and do not
poison an otherwise healthy paper runtime.

`stop()` is idempotent and does not invent broker-side shutdown semantics.

## Single-writer boundary

V0.1 deliberately binds the execution runtime to the thread that successfully
calls `start()`. Calls from another thread are rejected before touching the
SQLite execution store or paper adapter.

This is stricter than "put a mutex around SQLite": the current
`ExecutionStore` connection is thread-affine and the execution engine already
provides the durable ordering semantics. A future event-ingress queue may feed
this owner thread, but a second writer is not introduced.

## Reuse

No second execution engine, risk engine, journal, reconciliation model, shadow
engine, or broker adapter is created.

The orchestrator reuses:

- `build_paper_order_intent()`;
- `ShadowExecutionCapability`;
- `RiskGuard`;
- `ExecutionEngine`;
- `ExecutionStore`;
- factory-issued paper adapter capability.

## Safety boundary

This slice contains no live broker, no broker credentials, no trade unlock,
no Alpaca order path, no Moomoo/OpenD path, no HTTP/socket client, and no
production promotion.

It does not infer position size or decide whether a trade is attractive.
Those remain explicit upstream inputs and permissions.

## Remaining gates

Even after this component is validated:

1. the admission PR must be merged before this stacked branch can be promoted;
2. this runtime slice requires its own review and merge;
3. PR #148 live read-only market-data qualification must pass;
4. a realtime paper E2E must bind qualified live snapshot/currentness evidence
   to the upstream permission source;
5. multi-session paper soak and fault injection must pass.

`PAPER_AUTO_READY` remains NO until those gates close.
