# TickFlow Expert Cloud WebSocket: Sanitized Evidence V0.1 — 2026-10-12

## Why this is needed

STOCK RAZOR already successfully ran AWS REST `quotes.get`, 1/5/15/30/60-minute K-line and depth calls. That proves **SDK transport**, not persistent intraday streaming. During China's 11:30–13:00 lunch closure a no-event response is expected and must not be treated as provider failure or an admission signal.

The existing `scripts/probe_tickflow_isolated.py` 10/15/30/60-second isolated WS smoke tracks callback counts, unique timestamps, cached first snapshot candidates and later *update candidates*. But the AWS SSM private sanitizer previously discarded all of that metadata, and GitHub Actions reduced WS operations to `OBSERVED/NO_EVENTS_OBSERVED` without any counts. Thus market-open evidence was not safely inspectable.

## This PR: bounded, read-only, source-pinned observation

- Preserve only finite, bounded integer counters for `quote_callbacks`, `quote_events`, `unique_quote_samples`, `initial_snapshot_candidates`, `post_initial_update_candidates`, duplicate/out-of-order/invalid timestamps, unexpected symbols and error callbacks, plus enum-only connection and local subscription **call** result.
- Reject public or cached propagation of raw symbols, prices, exception content, API secrets, provider response objects, raw provider timestamps and latency distributions. No PII, balances, execution history or proprietary data leaves EC2 through this report.
- Force `subscription_ack_evidence=NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK`, `sample_latency_qualification=NOT_VERIFIED`, `post_initial_candidates_not_confirmed_live=true`, `provider_live_qualified=false`. Calling `subscribe` is **not** provider acknowledgement, even if callbacks occur.
- Synthetic tests execute the **actual embedded SSM sanitizer**, checking counter projection, malicious fields and typed sanitization. No network in tests.
- No default change: the Premium probe still requires explicit manual opt-in and `quote_only=false` plus a bounded 10/15/30/60-second `ws_seconds` to open a temporary streaming connection. `quote_only=true` remains the default and does not open WS.

## Real acceptance still missing

At least one independently observed **A-share trading-session** provider callback after subscription, beyond first possible cached snapshot, plus independently verified time semantics (Shanghai timezone, timestamp START/END), row parity vs Tencent/Eastmoney, repeat observations over time, 429 and reconnect behavior, account-shared quota/concurrency, and complete 15m/60m bars. A single 30-second test is still **REVIEW_ONLY**, never automatic TickFlow Source Arbiter promotion.

The user supplied TickFlow Expert plan is ¥199/month with advertised request ceilings. Monthly subscription does not imply infinite provider WebSocket concurrency. Use one shared connection per account, no automatic repeat storms. Any time the A-share market is closed or evidence is ambiguous, report `NOT_VERIFIED`, not a false failure or PASS.

Safety: `PAPER_AUTO_READY=NO`, `RADAR_ADMISSION=BLOCKED`, `SOURCE_ARBITER_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`. This PR alone performs **zero** cloud/network requests and changes no AWS service.
