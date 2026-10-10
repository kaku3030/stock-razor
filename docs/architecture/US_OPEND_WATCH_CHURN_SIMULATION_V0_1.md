# US OpenD watch churn stress simulation V0.1

This is an **offline, synthetic, research-only** stress model for the next step after the already merged `opend_subscription_review.py`. It does not discover full-market stocks, fetch data, query OpenD, subscribe/unsubscribe, allocate real market data quota, or execute trades.

## Inputs

- A bounded sequence of 1–240 hypothetical, already ranked US watch candidate frames (each 0–256 distinct `US.` symbols).
- `hypothetical_slots` (default 8), `min_consecutive_frames` (default 2), `max_changes_per_window` (default 4), and `window_frames` (default 6).
- **Frames are abstract observations, not minutes or seconds.** The sliding window is counted in frames, not real wall time. Do not interpret these limits as real provider rate limits.

## Simulation behavior

- A candidate must be present for at least two consecutive observations before a *hypothetical* addition.
- A hypothetically active watch must be absent for at least two consecutive observations before a *hypothetical* removal.
- Additions/removals share a bounded change budget across a sliding window.
- Existing simulated watches are not preempted simply because a newly ranked candidate is higher priority.
- Aggregate output counts hypothetical adds/removes, capacity blocks, rate-budget blocks, hysteresis blocks, and maximum simulated simultaneous watches.
- **No ticker lists or executable subscribe/unsubscribe instructions are output.** The function returns `subscription_changes=NONE`, `subtype_entitlement=NOT_VERIFIED`, `quota_qualification=NOT_VERIFIED`, `radar_admission=BLOCKED`, `live_trade=false` in all paths.

## What this cannot prove

The existing aggregate OpenD quota audit is not proof of per-subtype `QUOTE`, `K_1M`, `K_15M`, `K_60M` entitlement, independent OpenD connection ownership, provider rate limits, feed freshness or cloud deployment. Synthetic frames are not real market scans or actual provider subscription histories. This simulator does not authorize a real subscription manager.

Before considering any executor: verify current per-subtype entitlements and connection-specific quota, capture permitted market-hour event evidence, simulate replay/reconnect/cooldown under real documented limits, review a separate guarded executor, and preserve all trading and source-admission gates.

No AWS changes, paid provider requests, notifications or trades are made in this PR.
