# OpenD dynamic candidate dry-run preview

**Offline-only research boundary. No broker subscription mutation or deployment.**

The active AWS runtime script still creates one `OpenQuoteContext` and starts
fixed `CODES` through `LiveFeedRuntimeBridge.start`. The merged #582 manager
exists but is not yet wired into this live owner.

This PR adds `OpenDSubscriptionManager.preview_candidates`: it validates
US K_1M stream keys and external quota freshness, computes add/remove diffs,
and reports `PLAN_ONLY` without changing the candidate set or calling
the existing quote-context adapter. A pure plan is not an admission, quota proof,
actual subscribed state, or evidence of real-time push.

Next required steps:
1. Read current subscriptions/quota **from the same existing OpenD owner**.
2. Connect Radar candidate intent to the singleton's preview; observe dry-run
   add/remove plans over changing candidate sets.
3. Reconcile against external provider subscriptions and stale/history cache.
4. Perform separately authorized bounded AWS subscription mutation and recovery
   acceptance, preserving reserved symbols and existing data quality gates.

No paid request, provider mutation, new context or SIM order occurred.
`PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
`SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.
