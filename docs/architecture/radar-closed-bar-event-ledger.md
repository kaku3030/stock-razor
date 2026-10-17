# Radar closed-bar event ledger

Task `V51-C-CLOSED-BAR-EVENT-LEDGER-20261017` adds a bounded SQLite inbox for already-qualified, research-only signal candidates. It reuses the existing Stock Radar notification types and data-quality vocabulary; it does not create another Radar engine, AI executor, or notification transport.

## Event identity and admission

The unique event key is:

`provider|symbol|timeframe|bar_end_utc|rule_id|rule_revision|signal_kind`

The ledger additionally derives a stable bar ID from provider, symbol, timeframe, and provider bar-end time. Same-key/same-facts replay returns the original event. Same-key/different-facts replay raises a conflict and preserves the original row. Receipt time, process instance, and source sequence are retained only as first-observation provenance so an identical bar delivered again after a worker restart does not become a second event.

Before the transaction, the candidate must carry explicit `FRESH`, `CONFIRMED`, and `PASS` attestations from the caller's canonical source/session/freshness gate. The ledger independently checks IANA timezone validity; timezone-aware timestamps; closed and complete state; finite, positive, internally consistent OHLC; finite nonnegative volume/turnover; source/runtime identity; source SHA; evidence size and sensitive fields. This component does **not** calculate market-aware freshness thresholds, prove a provider's finality contract, or infer session state. Missing or unknown upstream attestations block.

## Persistence and wake semantics

The insert and capacity check run in one `BEGIN IMMEDIATE` transaction. Default outstanding capacity is 1,024 events; reaching it raises `EventQueueFull` before insert. Consumer claims are serialized across ledger instances and carry a fresh opaque lease token. Expired leases can be reclaimed with the same event idempotency key; retries are limited, and exhausted claims become `DEAD_LETTER`. Acknowledgment requires the current unexpired lease and a receipt ID.

This is **at-least-once wake delivery** across a crash after downstream acceptance but before acknowledgment. A future AI/event consumer must pass the unchanged `idempotency_key` to its own durable dedupe boundary; this ledger alone cannot prove exactly-once model invocation. The persisted candidate is committed before the consumer can claim it. Provider requests, AI calls, Discord sends, orders, and admission changes are outside this module.

## Current acceptance status

- Offline tests cover reject cases, duplicate replay after reopen, conflicting bar facts, capacity overflow, two-connection concurrent claims, lease expiry/recovery, retry exhaustion, dead letter, and acknowledgment ownership.
- The module is not wired into the provider runtime, AI wake service, or Discord notification sink. No live event has passed through it.
- `RADAR_ADMISSION=BLOCKED`, `SOURCE_ARBITER_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, and `LIVE_TRADE=NO` remain required.
- Local and CI tests prove code behavior only. Exact-main integration, actual AWS persistence/restart, AI dedupe, notification receipt, and cloud closed-bar evidence remain `NOT_VERIFIED`.
