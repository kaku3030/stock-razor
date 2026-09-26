# PAPER_EXECUTION_ADMISSION_V0.1

Status: implementation candidate, paper-only. Base: main at
`cbe833cf580390965848d01dbb05564b7905ffbe`.

## Purpose

Close the missing deterministic seam between an explicit upstream execution
permission and the existing `OrderIntent`. The seam does not decide whether a
trade is attractive and does not call a broker adapter.

The path is:

```text
Radar / Main Control evidence
-> explicit permission envelope
-> PaperOrderSpec
-> build_paper_order_intent()
-> OrderIntent
-> existing RiskGuard
-> existing ExecutionEngine
-> factory-issued paper adapter
```

## Boundary

This component owns only admission semantics and deterministic intent identity.

It does **not** own:

- market-data collection or freshness truth;
- strategy / Entry Gate / Main Control decisions;
- position or account truth;
- sizing inference;
- RiskGuard limits;
- order state transitions;
- broker credentials, trade unlock, sockets, HTTP, Alpaca, Moomoo or OpenD.

All account and broker targets emitted by V0.1 are hard-coded to `paper`.
V0.1 admits RTH limit intents only.

## Fail-closed admission

Admission requires all of the following:

- `canonical_permission == PASS`;
- `strategy_eligible is True`;
- `portfolio_admissible is True`;
- `execution_feasible is True`;
- no portfolio block reasons;
- the order's `evidence_snapshot_id` exists in permission evidence;
- decision, confirmation and earliest-executable timestamps are present;
- execution does not precede decision/confirmation;
- the order has reached its earliest executable time;
- `valid_until` is timezone-aware and still valid;
- session is exactly `RTH`.

UNKNOWN, missing or false values block admission.

## Identity / retry semantics

The paper intent ID is derived from:

```text
paper | strategy_id | observation_id | action_id
```

Mutable order fields are intentionally excluded. A retry that reuses the same
semantic action but changes quantity or price therefore retains the same
`intent_id`. Once the original intent is persisted, the existing Execution
Engine duplicate guard blocks a second mutation instead of silently creating a
new order.

A genuinely separate order action must use a different upstream `action_id`.

## Existing implementation reused

No new broker, journal, reconciliation, fill, risk or shadow engine is created.
The slice reuses:

- `OrderIntent`, `RiskGuard`, `ExecutionEngine`, `ExecutionStore`;
- factory-issued paper adapter capability;
- Live Shadow as a non-mutating observation path;
- existing Observation-compatible permission fields through a structural
  protocol instead of importing Radar as a runtime owner.

## Promotion

Passing these tests means only that an explicit permission can be admitted into
the already-qualified paper execution stack.

It does **not** qualify live market data, enable production, enable a real
broker, or authorize live trading.

Required later gates remain:

1. PR #148 live read-only market-data qualification;
2. realtime paper runtime orchestration;
3. multi-session paper soak and fault injection;
4. separate Moomoo read-only account-truth qualification before any live
   execution adapter is considered.
