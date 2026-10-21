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

## Durable research AI consumer

Task `V51-C-AI-RECEIPT-CONSUMER-20261017` adds `RadarAIEventConsumer.poll_once()` at the existing ledger boundary. The caller must explicitly inject an existing `GenerationBackend`, expected source SHA and worker identity, and set `enabled=True`. Default consumption is disabled, including event claims. No backend is constructed from credentials or environment; no runtime launcher/scheduler is changed. The current analyzer's automatic retries/fallbacks are not admitted as a verified single-request transport.

The same SQLite database now holds `stock_radar_ai_wake`, keyed by the original event idempotency key. Under a current event lease, one transaction checks the persistent call cap, prevents parallel/unresolved dispatch, and commits `STARTED` with a stable request ID and unique ownership token **before** calling `generate()`. A replay never starts a second consumer invocation for that key. A known result is validated and committed as `SUCCEEDED` **before** the event receipt is acknowledged. A crash between result persistence and ACK recovers that saved receipt after lease expiry without another model invocation, even if the original event is now old.

A crash/timeout after `STARTED`, a late result, malformed output, invalid/missing token evidence, or an uncertain storage outcome is `UNKNOWN`. No automatic model retry is safe because provider execution/charging may already have happened. Expired STARTED requests become UNKNOWN on read/reservation. Any STARTED/UNKNOWN request blocks new dispatches in that database, even for other bars. Resolving an uncertain provider request requires future evidence-based reconciliation; no reset/retry escape hatch is added here.

The request accepts only fresh OpenD canonical closed-bar observations matching the expected source SHA. The prompt contains a fixed bounded selection of facts, not arbitrary event evidence. Output must be exactly the unchanged event ID, `assessment=WATCH|NO_SIGNAL`, and nonempty evidence field names chosen from OHLCV/turnover/bar-end facts. Extra fields, entry/exit/order instructions and invented evidence fields are rejected. Raw model text, exceptions, model metadata and secret fields are not persisted. Token evidence reuses `src.llm.usage` normalization and requires complete nonnegative consistent counts. Token counts are not official currency charges: cost status stays UNKNOWN.

Limits are conservative and constructor-bound: one total committed invocation by default (at most 100), 10-second request deadline (at most 60), 512 requested output tokens (at most 2,048), bounded prompt/output bytes, and event age no more than 120 seconds. The call cap survives process restart and is not a per-process counter or an automatically renewed budget. Generation timeout/output limits are forwarded through the shared backend contract; the consumer does not kill a stuck synchronous backend. The unique durable intent prevents redispatch while it is stuck, but physical provider request counts, hard timeout/cancellation, fallback/retry suppression, provider-enforced monetary limits and independent runtime liveness must still be verified before production enablement. This implements at-most-once consumer dispatch, not a claim of exactly-once provider billing, guaranteed execution, or unattended service completion.

The table is additive and created idempotently in the existing database. Existing event rows/lease semantics are preserved. Roll back by disabling the optional consumer/reverting code while retaining receipt rows; deleting/recreating receipt storage would destroy dedupe and budget evidence. AI wake delivery to a live model, Discord dispatch, source/Radar/paper/trading admission and AWS restart/recovery remain NOT_VERIFIED.

## Optional single-request research transport

Task `V51-C-SINGLE-REQUEST-BACKEND-20261017` supplies `ResearchAIRequestBackend` through the existing `GenerationBackend` interface. Both backend and consumer default to disabled. An authorized runtime caller must supply the provider, model and credential explicitly and inject it into the durable consumer. This change adds no environment setting, credentials, runtime launcher, scheduler, model smoke request, notification or order path.

The fixed worker uses the installed official OpenAI Python SDK for the allowlisted OpenAI/DeepSeek hosts. SDK retries are explicitly zero; HTTP redirects, ambient proxies, SDK debug configuration, streaming generation, tools, arbitrary endpoints, model fallback and extra generation settings are excluded. Each admitted invocation issues one non-streaming chat-completion request, with bounded prompt/output tokens and successful response bytes. Unsupported provider/model behavior fails closed; no compatibility retry occurs. OpenAI receives max_completion_tokens, DeepSeek receives max_tokens. The request identity is for client tracing, not a claim of provider idempotency or exactly-once charging.

A fixed Python module runs the SDK call in a local child process, with credentials passed over stdin and no shell/arbitrary command. The supervising backend accounts for process-start time in the 1–60 second deadline, kills an unfinished child at deadline, and bounds reaping to two additional seconds. Raw provider errors, worker stderr, metadata and credentials are discarded. Only text and three validated token counts cross the result boundary; the consumer separately validates event identity/research schema and persists its receipt before ACK. If process launch, cleanup, provider work, response validation or completion is uncertain, the durable UNKNOWN barrier prevents automatic retry. A parent crash can leave remote/provider work or a local orphan unresolved; this code does not replace an independent service supervisor.

Offline tests exercise the real installed SDK with HTTP MockTransport: 408/409/429/5xx, connection errors and timeouts each make one request; redirects are not followed. They also kill an actual sleeping child, reject incomplete/oversize/token-invalid responses and unsafe configuration, and exercise consumer → SDK transport → persistent receipt → reopen/ACK recovery without repeated dispatch. This is code-level evidence only. No live credentials or model request were used. Provider-enforced monetary limits, actual charges/balances, authorized live-model compatibility, process recovery on AWS, continuous supervision and Discord delivery remain NOT_VERIFIED. Token/call caps are not a currency budget.

Official contracts reviewed: https://github.com/openai/openai-python (SDK retries and timeouts) and https://api-docs.deepseek.com/api/create-chat-completion/ (OpenAI-compatible non-streaming chat and max_tokens). Reused installed SDK and existing generation/ledger/usage contracts; no external implementation copied and no new dependency introduced. The existing analyzer retrying router remains outside this transport.

Rollback: disable the optional consumer/backend and revert the code while retaining ledger receipt/budget rows. No cloud state or database migration is added. All source/Radar/paper/trading gates remain closed.

## Persistent source intake and supervised consumer loop

Task `V51-CG-DURABLE-CONSUMER-RUNTIME-20261018` extends the existing AWS US source-worker installer with `closed_bar_events_enabled=false` (workflow input) / `CLOSED_BAR_EVENTS_ENABLED=false` (installer). Only an explicit true choice creates a systemd-owned `StateDirectory=stock-razor-us-radar`, mode 0700, without changing existing heartbeat-file permissions. The worker uses `STATE_DIRECTORY/closed-bar-events.sqlite` and injects that ledger into the existing canonical worker. It publishes categorical `bar_event_queue` counts alongside the existing source/worker SHA and ingress status. Default-off opens no database. All existing restart consent, exact-main/source SHA, sandbox and data-admission gates remain required; no deployment was dispatched here. Network isolation remains enabled, and this source service never creates a model backend. Enabled collection adds the existing repository calendar version exchange-calendars==4.13.2 to the isolated environment, checks XNYS construction before service installation, and rejects UNKNOWN calendar inference at runtime before opening the ledger. Default-off retains the minimal dependency set.

The optional `run_ai_consumer()` entry in `ai_consumer_runtime.py` accepts a caller-owned persistent ledger, admitted backend, expected source SHA, worker SHA, status path and stop path. It defaults to disabled, one cycle and a 120-second total envelope. Cycles, duration and polling waits are bounded; it requires room for the configured call timeout plus 30 seconds of bookkeeping before starting a poll. The caller owns exactly one writer per status path and any process/service supervisor. No new scheduler, backend discovery, credential loader or paid execution switch is added. A separately authorized runtime wrapper must supply an admitted backend; an independent network-capable consumer service is not installed by this change.

Before each enabled poll it atomically publishes private categorical telemetry, runtime ID, sequence and a poll deadline. Failure to write status blocks dispatch. Subsequent status carries queue/receipt counts, consumer state and remaining durable call allowance; these are not official token/currency bills, and cost remains UNKNOWN. Ledger summaries use a single read-only SQL snapshot; they neither renew leases nor reconcile expired model intent. Consumer UNKNOWN/BLOCKED/IN_PROGRESS halts the bounded loop. Known successful receipt/ACK recovery still reopens the same database and never redispatches the model. STOP-file existence or existing AUTONOMY_STOP=true stops between polls; it cannot recall an already sent remote request. Call timeout/cleanup still belongs to the admitted single-request backend. Process crash/orphan handling and actual AWS watchdog recovery remain NOT_VERIFIED.

`assess_runtime()` and `python scripts/audit_radar_ai_runtime.py --status-file <file> --worker-sha <SHA> --source-sha <SHA>` provide independent read-only assessment. Missing/corrupt/oversized/unsafe/mismatched/future evidence returns UNKNOWN; old heartbeat returns STALE; a recorded poll past its bounded deadline returns STALLED; unknown/expired intent returns BLOCKED; dead letters or old queued events return DEGRADED. Disabled, stopped and exhausted loops are reported explicitly. OBSERVED/BUSY indicate a fresh recorded state, never proof of continuous execution, model completion, source admission or cloud acceptance. The audit reads at most 64 KiB and emits no provider exception, model text, keys or raw unrecognized fields. It sends no notifications. G can feed these categorical outcomes into the existing authorized alert path later.

Status/stop artifacts are rejected if they alias the ledger database or WAL/SHM journals, protecting dedupe and budget evidence from accidental atomic replacement. A stale backlog is reported, not silently reclassified as fresh or discarded; the existing 120-second event gate still applies. Runtime restart, production shared-storage ownership, monetary admission, real model/Discord receipts and the full D1/1H/15m unattended acceptance remain separate work. The source sandbox must not be relaxed to give the model network access.

Offline coverage executes the extracted real installer prefix with default-off and enabled modes, persists/reopens the ledger, exercises receipt-before-ACK recovery and uncertain-outcome restart, status-write failure before claim, cooperative stop before/during calls, finite cycles/runtime budget, and adversarial monitor/CLI inputs. Official systemd contract: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html (StateDirectory and sandbox writable exceptions). No model SDK or new application dependency is introduced; the existing calendar dependency is added only to enabled source-worker environments. No external implementation copied. Roll back by disabling event collection/consumer and reverting code; retain the StateDirectory/receipt rows, since removing them destroys budget/dedupe evidence.

## Current acceptance status

- Offline tests cover reject cases, duplicate replay after reopen, conflicting bar facts, capacity overflow, two-connection concurrent claims, lease expiry/recovery, retry exhaustion, dead letter, and acknowledgment ownership.
- Exporter → canonical poller → persistent SQLite/consumer claim is verified with offline fixtures, including reopen/replay, stale/future/invalid facts, full queues and real SQLite transaction failure/retry.
- The optional intake/consumer are not enabled in a runtime launcher or AWS. Exporter → poller → reopened SQLite → offline GenerationBackend → durable result/ACK is covered; no live model or Discord sink is wired.
- `RADAR_ADMISSION=BLOCKED`, `SOURCE_ARBITER_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, and `LIVE_TRADE=NO` remain required.
- Local and CI tests prove code behavior only. Exact-main integration, actual AWS persistence/restart, AI dedupe, notification receipt, and cloud closed-bar evidence remain `NOT_VERIFIED`.


## Symbol quality isolation and worker-only deployment

Known turnover-derived quality flags (VWAP_OUTSIDE_BAR_RANGE and PARTIAL_TURNOVER)
quarantine only the affected symbol/timeframe. A known snapshot-health failure
skips that whole symbol before any event candidate is made. Unknown health flags,
bad provenance, invalid timestamps, incomplete grids, and storage/queue/conflict
failures retain batch-wide fail-closed behavior. Known flags never mask structural
bar failures. No quarantined facts are labelled PASS or persisted as valid events.

Healthy polls between 15m/1h boundaries report NO_NEW_CLOSED_BAR, not a data
failure. PARTIAL identifies valid intake with explicit isolation reasons.
All due candidates quarantined, or all snapshots quarantined, remains BLOCKED.
The next source sequence rechecks isolation; repaired bars inside the freshness
window can enter once, while existing facts dedupe. Unchanged polls keep isolation
reasons, exposed in admission_diagnostics.bar_event_quarantine_reasons.

The existing Radar deployment workflow accepts optional expected_source_sha.
It defaults to expected main, preserving old callers. An explicit full SHA pins
the already-running LiveFeed; the remote heartbeat must match exactly before
installation. This updates only the isolated Radar worker, avoiding an acquisition
restart during RTH. Worker and source versions are intentionally independent;
their exact identities, schema loading, daily-history lineage and unchanged safety
gates are verified. This option does not authorize LiveFeed restarts or trading.

Rollback: deploy the previous reviewed worker revision with the same exact source
pin through the controlled deployment path; retain the event StateDirectory and
receipt rows. Do not delete the ledger or relax admission to recover availability.
