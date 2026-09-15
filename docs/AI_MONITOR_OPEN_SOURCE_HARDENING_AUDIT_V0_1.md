# AI Monitor — Open-Source Hardening Audit V0.1

Status: ACTIVE AUDIT / IMPLEMENTATION TRACK

This document governs the Build-vs-Borrow hardening track for the AI portfolio monitor / realtime_monitor. It does not promote any external implementation to production merely because it is mature or popular, and it does not treat a successful repository migration as Shadow/LIVE readiness.

## Governing rule

Every external component follows:

`DISCOVER -> AUDIT -> EXTRACT -> ADAPT -> HARDEN -> ADVERSARIAL TEST -> REPLAY/OOS -> SHADOW LIVE -> PROMOTE`

External components are classified as one of:

- `DIRECT_ADOPT`
- `ADAPT`
- `BORROW_TEST`
- `RESEARCH_ONLY`
- `REPLACE_WITH_OURS`
- `REJECT`

Core Stock Razor / AI Monitor semantics remain ours: Portfolio State, Ownership/Exposure/Add Right, Leadership/RS, Market/Risk State, Trigger semantics, Risk Budget, and Evidence -> Gate -> Narrative.

## Current repository findings

### P0 — realtime monitor source is now auditable in PR #37

PR #37 (`feat/stock-razor-monorepo`) imports the previously local Moomoo/Futu realtime monitor into `realtime_monitor/server.py`, removes the hard-coded account identifier, adds explicit product boundaries, and preserves the previously validated monolith instead of refactoring it during migration.

Migration audit conclusion: the broker boundary is read-only in the imported monitor. The current source uses account/position and quote reads; review found no `place_order`, `modify_order`, or `unlock_trade` path. This is migration evidence only, not production promotion.

Formal Ownership Right / Exposure Right / Add Right, Leadership persistence, and Edge/Risk Budget remain incomplete contracts and must not be represented as finished merely because the monitor source is now in Git.

### P0 — Live Feed Reliability foundation exists and is usable

PR #28 added a provider-neutral streaming capability boundary, immutable provider event/identity models, single-writer LiveFeedController, desired subscription registry, nonblocking provider command boundary, immutable snapshots, and LiveFeedHealth facts.

Current deliberate gaps in the controller remain:

- DeliveryMode / entitlement qualification (F04 remains provider-semantic P0)
- CurrentnessBoundary
- Continuity
- RecoveryCandidate
- cache live-trust revocation
- final health aggregation policy
- LIVE promotion
- final provider-worker isolation policy

These gaps are not cosmetic: the frozen contract explicitly forbids `CONNECTED -> LIVE`, `RECONNECTING -> LIVE`, and forbids DELAYED/UNKNOWN delivery modes from reaching LIVE.

### P0 — Legacy/runtime alert path can evaluate numeric quote values without an explicit freshness hard gate

`src/services/alert_service.py` and `src/agent/events.py` obtain a realtime quote, validate that a numeric price/change exists, then evaluate threshold conditions. They expose/extract a data timestamp, but the current threshold path does not first prove that the quote is fresh/current enough for an actionable realtime alert.

Risk: a stale-but-numeric quote can satisfy a price/percent threshold unless upstream provider behavior happens to prevent it. Data Health must be a hard gate, not an incidental provider assumption.

PR #39 now contains an isolated fail-closed quote-currentness contract and adversarial fixtures. On head `596c8601167c7c1da0e5455b1f5fd3df94642d90`, both repository CI and Research Radar Tests passed. Promotion is `VALIDATING` for the isolated contract only: it is not yet wired into `EventMonitor` / `AlertService`.

A separate upstream semantic defect remains: `DataFetcherManager._parse_realtime_timestamp()` currently treats timezone-naive provider timestamps as UTC. Downstream future-time rejection is defense-in-depth, not a substitute for repairing provider timestamp normalization.

### P0 — imported Unified Data Health is date-current, not intraday-current

The imported `realtime_monitor/server.py` calls `_data_health_check_core()` as the single freshness authority. The current implementation determines `OK` by comparing the **date** of `latest_bar_time` with the expected latest trading date.

During a REGULAR session, a 15m or 1h stream can stop progressing early in the day yet remain `OK` for hours because the bar still carries today's date. The snapshot `update_time` is exposed but is not age/currentness-gated either.

Required repair:

1. separate trading-date/session validity from within-session progress/currentness;
2. inject deterministic clock/session evidence in tests;
3. define timeframe-aware progress expectations or bounded lag without guessing provider bar-boundary semantics;
4. empirically verify Futu/Moomoo `time_key` and snapshot timestamp semantics before hard-coding exact timing rules;
5. expected silence (overnight/weekend/holiday/session startup/half-day) must not create false outages;
6. same-day stale-but-numeric evidence must never receive actionable `OK` authority.

Permanent regressions:

- `regular_session_same_day_15m_stuck_is_blocked`
- `regular_session_same_day_1h_stuck_is_blocked`
- `weekend_expected_silence_not_false_stale`
- `session_startup_before_first_expected_bar_has_explicit_grace`
- `stuck_snapshot_time_cannot_gain_current_authority`

### P0 — unhealthy observation currently advances directional baseline truth

`run_primary_trigger_cycle()` always persists `previous_snapshot = current_snapshot` after trigger/AI-gate construction, including when current Data Health is non-OK.

Directional AI is blocked while health is bad, which is good, but the stale/unhealthy timeframe state still becomes the next comparison baseline. When data recovers, comparison against that poisoned baseline can create artificial directional events.

Required repair must keep observation from authority. Preferred contract:

- persist unhealthy observations for diagnostics/journal;
- keep a separately labeled `last_known_good_snapshot` (or equivalent trusted baseline);
- only trusted evidence advances directional comparison authority;
- recovery passes an explicit reconciliation gate before normal directional triggering resumes;
- restart preserves the same trust distinction.

Permanent regressions:

- `bad_health_observation_does_not_replace_last_known_good_baseline`
- `bad_to_good_recovery_does_not_fabricate_directional_change`
- `recovery_requires_reconciliation_before_normal_trigger_authority`
- `restart_preserves_last_known_good_authority`

### P0 — Portfolio State can silently lose a held symbol

`get_portfolio_state()` currently skips a row when `qty` cannot be parsed/is non-finite and still returns `ok=True`. Separately, `compare_analysis_states()` compares only the intersection of previous and current symbol keys; added/removed symbols are outside the current trigger contract.

Combined risk: a partial or malformed-but-RET_OK account response can make a real holding disappear from monitor scope without a portfolio-health event or reconciliation event.

Required repair:

1. malformed required portfolio fields produce DEGRADED/BLOCKED evidence, never silent row deletion;
2. record raw row count, accepted row count, rejected row reasons, and account/source identity;
3. only a trusted account snapshot may advance portfolio membership truth;
4. reconcile position membership and material quantity/cost changes explicitly;
5. a symbol missing from an untrusted snapshot keeps prior membership authority and surfaces risk/degraded evidence;
6. trusted quantity/cost changes are journaled even if directional AI is unnecessary.

Permanent regressions:

- `malformed_qty_row_cannot_silently_disappear`
- `untrusted_missing_symbol_keeps_prior_membership_authority`
- `trusted_position_removal_reconciles_deterministically`
- `trusted_new_position_enters_monitor_scope`
- `quantity_or_cost_change_is_journaled`

### P1 — symbol-wide cooldown can suppress a distinct material event

`apply_event_suppression()` correctly has event fingerprints and permits severity escalation above the previous severity, but after fingerprint dedupe it also applies a symbol-wide cooldown. A different material event with the **same** severity can therefore be suppressed inside the earlier event's cooldown. A new HIGH deterioration must not disappear merely because another HIGH event fired minutes earlier.

Required follow-up after P0 trust fixes: define a material-change/risk-escalation override with deterministic suppression tests. Do not solve this by simply disabling cooldown.

## Open-source extraction decisions

### VeighNa / vn.py — `ADAPT`

Borrow/port the proven event-queue and bar-aggregation shape. Do not import its trading execution semantics. Our bar layer must remain session-aware for A-share lunch breaks and U.S. premarket/regular/after-hours boundaries.

### PKScreener — `BORROW_TEST` + selective `ADAPT`

Borrow the data-freshness regression scenarios:

- fresh realtime data beats stale cache;
- stale data is rejected;
- timestamps must be current for the intended decision horizon;
- fallback is explicit and only used when realtime is unavailable;
- database failure must not poison the fresh realtime path.

VCP/pattern code is a Radar concern and should be handled separately.

### TradingAgents — `ADAPT`

Borrow structured-output, checkpoint/resume, persistent decision-log, and bull/bear counter-thesis orchestration ideas. Do not adopt autonomous BUY/SELL decision semantics.

### Freqtrade — `RESEARCH_ONLY` (GPL code boundary)

Borrow the operational idea of Protection/Cooldown state, not source code. Cooldown must allow severity escalation or material state change to break suppression.

### NautilusTrader / LEAN — `RESEARCH_ONLY`

Borrow live/replay parity, reconciliation, event-driven boundaries, cache/portfolio/message-bus separation, and restart-recovery design. Do not migrate the project onto either engine in P0.

## Revised P0 implementation sequence

0. **Land/audit the source boundary** — PR #37 makes the monitor auditable in-repo; migration is not LIVE promotion.
1. **DeliveryMode F04 closure** — prove/normalize provider delivery mode; UNKNOWN/DELAYED remain fail-closed.
2. **Currentness hard gates**
   - wire the isolated PR #39 quote-currentness contract into actionable legacy alert consumers;
   - add monitor-native session/timeframe progress currentness for 15m/1h and quote/snapshot authority.
3. **Trusted Portfolio State + baseline authority** — fail closed on malformed account evidence; membership reconciliation; last-known-good vs observed snapshot separation.
4. **Continuity + RecoveryCandidate** — two-phase recovery; duplicate/correction/backfill cannot restore LIVE.
5. **Restart Reconciliation** — restart resets live trust to zero; desired subscriptions/portfolio/alert protection state are reconciled explicitly.
6. **Protection State** — cooldown/dedup becomes stateful suppression with escalation/material-change overrides.
7. **Rights / Legacy / Secular Core contracts** — formal Ownership Right, Exposure Right, Add Right and position rehabilitation state transitions consume only trusted evidence.
8. **AI checkpoint + Decision Journal hardening** — structured review, resumable model chain, persistent evidence/state-change log; single-writer deployment or a real inter-process/storage transaction boundary.
9. **Shadow Live** — same evidence/trigger/state-machine code path as Replay; no production promotion until false-positive/false-negative and failure-injection review passes.

## Permanent regression additions

Minimum cross-track regression set:

- `fresh_quote_allows_evaluation`
- `stale_numeric_quote_cannot_trigger`
- `missing_quote_time_cannot_be_promoted_to_fresh`
- `delayed_delivery_never_live`
- `unknown_delivery_never_live`
- `fresh_received_at_with_stuck_source_progress_not_live`
- `stale_cache_cannot_masquerade_as_realtime`
- `db_failure_does_not_poison_live_feed`
- `a_share_lunch_expected_silence_not_outage`
- `us_after_hours_semantics_not_mixed_with_regular_session`
- `restart_resets_live_trust`
- `duplicate_post_reconnect_event_does_not_prove_continuity`
- `same_progress_correction_does_not_prove_continuity`
- `cooldown_suppresses_duplicate_but_not_severity_escalation`
- `cooldown_does_not_suppress_distinct_material_high_event`
- `bad_health_observation_does_not_replace_last_known_good_baseline`
- `untrusted_missing_symbol_keeps_prior_membership_authority`

## Scope boundary

This track does not add automatic order placement or execution permission. AI Monitor remains decision support and alerting only.

## Source-code availability note

The realtime monitor source is now available for repository audit on PR #37 / branch `feat/stock-razor-monorepo`. The old statement that the standalone monitor body was unavailable is obsolete. Full hardening should now use that source directly, preserve migration characterization evidence, and avoid broad refactoring until the P0 trust contracts above have permanent tests.
