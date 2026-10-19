# STOCK RAZOR | OpenD completion-first priority and acceptance (2026-10-19 JST)

**Canonical priority:** Existing `AGENTS.md` + self-improvement skill. This is an execution checklist and evidence snapshot, **not** a replacement authority, model training, background agent or trading permission.

## What to finish first

1. **P0 — Windows OpenD local**: complete the data contract and its verifiable acceptance **before unrelated new features**. The local gateway, owning connection, subscription entitlement, continuous observed 1m pushes, closed 5m/15m/1H, historical D1, session semantics and reconnect/recovery are independent gates. If the local machine is offline, mark `LOCAL_RUNTIME_UNAVAILABLE`, do not treat the cloud as proof of local completion.
2. **P0-RTH exception — AWS OpenD live-observation window**: during US regular market hours, prioritize time-limited **read-only cloud observation** of new provider callbacks, current source timestamp, full 1m→5m→15m→1H progression, close/finality evidence and Radar poll validity. Do this **without suspending** the local P0 stream or taking over TickFlow's separate owner. If no new signal is possible, focus on diagnosing the single first blocker, not hourly identical retries.
3. **P1 — AWS OpenD cloud parity**: after local qualification, verify the **actually deployed** SHA, owning subscription, exact provider `futu/opend` and session flags, D1 historical cache delivery, stream convergence and reconnect. Cloud `HEALTHY`/CI pass, correct port, source cached rows and `REALTIME` mode alone cannot promote business acceptance.
4. **Do not spawn extra workstreams**: maintain existing CN TickFlow work in its own lane; avoid broad unrelated PRs until OpenD P0 gates close. PR #851 subscription readback and #749 bounded historical D1 are existing **unmerged** candidate implementations; first reconcile those against latest main, don't duplicate their implementation.

## Snapshot of direct evidence on 2026-10-19, about 23:29 JST

| Place | Verified observation | Not proven |
|---|---|---|
| Windows `DESKTOP-2SLTODA` | `moomoo_OpenD` process alive, PID 24968; Windows TCP listener `127.0.0.1:11111` owned by PID 24968. | Authorized OpenD quote login, QOT_RIGHT, provider subscribe ownership, historical D1, fresh closed OHLCV and disconnect recovery. |
| AWS / OpenD MCP | `get_livefeed_health` `HEALTHY`, `delivery_mode=REALTIME`, `realtime_delivery_evidence=true`, `last_push_utc=2026-10-19T14:28:54Z`; deployed `repo_sha=896f05d4f01763a75413e4cf40d40288e4435c0e`. | Provider close/finality `UNPROVEN`. A healthy process is not accepted data for trading. |
| AWS / Radar MCP | `get_us_research_brief(US.QQQ,US.NVDA)` `BLOCKED` with reason `RADAR_CURRENT_POLL_NOT_VALID`; market and Radar source sequences both 21545 in observed packet. | Radar full live-analysis and actionable signal admission. Current match at observation does not prove permanent sequence alignment. |
| Canonical GitHub main | `7e1ca0edc7be2c099bf3638ead49f994a2cefde1` | Cloud version match: **MISMATCH** with deployed OpenD SHA; actual deployment remains independently controlled. |

These are time-bound observations, not promises or a latest-forever dashboard. Before a new decision refresh current GitHub SHA + provider runtime timestamps.

## Specific nonduplicate execution queue

- **L0**: Read only the **owning Windows** OpenD client + entitlement/subscription evidence without modifying provider state. Record runtime/session/account entitlement as sanitized `PASS/BLOCKED`; if the client is alive but permission unknown, diagnose rather than reconnect or resubscribe blindly.
- **L1**: Capture a bounded market-session Windows sample for `QQQ` + `NVDA` across **1m/5m/15m/1H/D1**, including per-bar provider timestamps, current session, `is_closed`, finite OHLCV and provenance. No other feed fallback. Do not count a cached push as realtime qualification.
- **L2**: Prove 1m progression, 15m and hourly boundary closure with fresh 2-sample witness and controlled disconnect/recovery; do not claim finality from one Boolean flag. Attach exact timestamps and the local executable/source SHA.
- **C0 (RTH)**: Diagnose the **new cloud Radar blocker `RADAR_CURRENT_POLL_NOT_VALID`** (rather than redo a source-sequence probe that already matched) and isolate underlying poll status + `bar_closure=UNPROVEN` separately; minimal targeted tests only.
- **C1 (after L2)**: Reconcile PR #749 historical D1 and PR #851 subscription readback with current main on non-conflicting integration branch, protect all gates, pass exact-head CI before merge. Deployment and real AWS MCP readback are separate stage gates.
- **C2**: Independent AWS exact-deployed-SHA audit and provider/Radar 5-timeframe output. Verify subscription quota/ownership, reconnect and provenance with real timestamps. Only mark qualification PASS when all independently observed; never automatically lift live-trade gates.

## End-state acceptance (MUST all be independently evidenced)

- Local: five cycles (**1m/5m/15m/1H/D1**), own OpenD provider, rights and session identity, validated time grids, source timestamps, closed/final bars; continuity and reconnect across the actual appropriate trading session.
- AWS: same data contract and exact deployment SHA, provider source, proven close/finality, full current research and cross-end equivalence within a documented tolerance.
- Communication: per-run **fetch, analysis, radar and total response latency measured**, source and bar-end listed; local and cloud status tracked separately, with explicit `NOT_VERIFIED` until proven.
- CI green + successful AWS command ≠ real-data acceptance. `SOURCE_ARBITER_ADMISSION=BLOCKED`, `RADAR_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO` remain unchanged.

## Ownership and coordination

**Main Control** owns aggregate priority, exact-main PR/CI, AWS deploy acceptance and conflict arbitration; **OpenD US lane** owns L0–L2 and C0–C2 data evidence; **TickFlow CN** continues its separate pipeline. Every new OpenD-related chat must automatically read this current-main file and registered `US-001`–`US-005` historical failures before scheduling another probe. Write a compact, non-private status delta to Context Manager via the existing owner-gated GitHub #924 publication route when one of these gates changes.

No new paid data, keys, subscriptions, IAM changes or orders are authorized by this priority document.
