# OpenD Runtime Acceptance Matrix (2026-10-21)

This matrix records the current boundary between source health, subscription control, and
strategy admission. It is intentionally fail-closed.

| Area | Current evidence | Status | Next proof |
| --- | --- | --- | --- |
| Subscription capacity | `OpenDSubscriptionQuota` and fake adapter tests validate quota arithmetic and stale/unverified rejection | Offline verified | Execute `query_subscription` from the same AWS owner and persist readback |
| Runtime add/remove | `OpenDSubscriptionManager.add/remove/update_candidates` are covered by deterministic tests | Preview only in AWS | Run a bounded add, read back ownership, wait at least one minute, then remove and read back |
| Disconnect recovery | Isolated Wave 2 proxy harness and manager `recover()` exist; cloud owner still has no callback/loss proof | Harness only | Correlate private OpenD reconnect logs, callback counters, sequence continuity, and post-restore data |
| Source delivery | AWS livefeed heartbeat reports `CONNECTED`, `REALTIME`, and `bar_closure=PROVEN` | Observed | Keep per-symbol freshness and closure evidence |
| Radar promotion | Current cloud Radar returns `poll_status=BLOCKED`; promotion and paper execution remain disabled | Blocked by design | Qualify the bar event snapshot and all symbol health gates |

The official OpenD contract requires quota/readback to be treated separately from data
delivery. A successful subscription call is administrative evidence; it does not prove that
the provider delivered a usable bar. The runtime therefore keeps subscription control,
source acceptance, bar closure, and strategy admission as separate states.

No production `subscribe`/`unsubscribe` mutation is enabled by this document.
