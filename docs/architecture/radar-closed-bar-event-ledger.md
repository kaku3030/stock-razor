# Radar closed-bar event ledger

Task `V51-C-CLOSED-BAR-EVENT-LEDGER-20261017` adds a bounded SQLite inbox for already-qualified, research-only signal candidates. It follows the existing Stock Radar data-quality vocabulary; it does not create another Radar engine, AI executor, or notification transport.

## Event identity and admission

The unique event key is:

`provider|symbol|timeframe|bar_end_utc|rule_id|rule_revision|signal_kind`

The ledger additionally derives a stable bar ID from provider, symbol, timeframe, and provider bar-end time. Same-key/same-facts replay returns the original event. Same-key/different-facts replay raises a conflict and preserves the original row. Receipt time, process instance, and source sequence are retained only as first-observation provenance so an identical bar delivered again after a worker restart does not become a second event.

Before the transaction, the candidate must carry explicit `FRESH`, `CONFIRMED`, and `PASS` attestations from the caller's canonical source/session/freshness gate. The ledger independently checks IANA timezone validity; timezone-aware timestamps; closed and complete state; finite, positive, internally consistent OHLC; finite nonnegative volume/turnover; source/runtime identity; source SHA; evidence size and sensitive fields. This component does **not** calculate market-aware freshness thresholds, prove a provider's finality contract, or infer session state. Missing or unknown upstream attestations block. Both closure flags are required constructor inputs. Nested evidence is validated as a detached JSON snapshot, and persistence always uses that snapshot; subsequent caller mutations cannot rewrite the validated facts or inject sensitive evidence.

## Persistence and wake semantics

The database argument is required; callers must explicitly choose a persistent path or opt into `:memory:` for a temporary test. The insert and capacity check run in one `BEGIN IMMEDIATE` transaction. Default outstanding capacity is 1,024 events; reaching it raises `EventQueueFull` before insert. Consumer claims are serialized across ledger instances and carry a fresh opaque lease token. Expired leases can be reclaimed with the same event idempotency key; retries are limited, and exhausted claims become `DEAD_LETTER`. Acknowledgment requires the current unexpired lease and a receipt ID.

This is **at-least-once wake delivery** across a crash after downstream acceptance but before acknowledgment. A future AI/event consumer must pass the unchanged `idempotency_key` to its own durable dedupe boundary; this ledger alone cannot prove exactly-once model invocation. The persisted candidate is committed before the consumer can claim it. Provider requests, AI calls, Discord sends, orders, and admission changes are outside this module.

## Optional canonical poller integration

Task `V51-C-CANONICAL-EVENT-INGRESS-20261017` connects the existing `CanonicalSnapshotRadarWorker` to this ledger through its optional `event_ledger` constructor argument. The caller owns and closes the ledger. Without injection, the worker opens no database and retains its existing research-only behavior. No scheduler, environment setting, deployment, model call or notification sink is activated.

After the existing exact-SHA and sequence preflight, `canonical_bar_events.py` requires realtime delivery, proven closure, a regular OpenD US session, an independently confirmed active exchange-calendar phase, fresh export/snapshot/source-minute times, normal unflagged health, native turnover, no fallback, and the existing current-session 15m/1h closed-grid qualification. Missing calendars and unknown states fail closed. It records only the latest closed 15m/1h bucket when that bucket ended within the evaluator's active-age budget (default 120 seconds). It never reclassifies an old hourly bucket as a new event because a heartbeat or source sequence changed. Session-grid warmup before the first complete hour, pre/postmarket and the exact/post-close phase remain blocked in this initial adapter; D1 and on-demand 5m intake are not implemented.

These events use `rule_id=canonical_closed_bar`, `rule_revision=1`, and `signal_kind=closed_bar_observation`. They are facts for later research evaluation, not strategy entry/exit candidates or a completed D1/1h/15m decision. Changing runtime instance, export sequence or observation time does not change their immutable payload.

All candidates are validated before the first insert. Each bar then uses the ledger's existing committed transaction. A storage/capacity/conflict failure returns bounded diagnostic codes and prevents the worker's successful source watermark/file cache from advancing. Already committed bars remain durable; same-source retry dedupes them and retries the rest. This is per-bar durability, not an atomic multi-symbol batch. A backlog that outlives the freshness window is blocked, not silently replayed as current; durable historical catch-up policy and production alerting are still required.

The additive `bar_event_ingress` output is `null` when disabled; otherwise it reports status, new/duplicate counts and bounded reason codes. Research evaluation success remains separate from signal admission.

## Current acceptance status

- Offline tests cover reject cases, duplicate replay after reopen, conflicting bar facts, capacity overflow, two-connection concurrent claims, lease expiry/recovery, retry exhaustion, dead letter, and acknowledgment ownership.
- Exporter → canonical poller → persistent SQLite/consumer claim is verified with offline fixtures, including reopen/replay, stale/future/invalid facts, full queues and real SQLite transaction failure/retry.
- The optional adapter is not enabled in a runtime launcher or AWS. AI wake and Discord are not wired; no live event has passed through it.
- `RADAR_ADMISSION=BLOCKED`, `SOURCE_ARBITER_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, and `LIVE_TRADE=NO` remain required.
- Local and CI tests prove code behavior only. Exact-main integration, actual AWS persistence/restart, AI dedupe, notification receipt, and cloud closed-bar evidence remain `NOT_VERIFIED`.
