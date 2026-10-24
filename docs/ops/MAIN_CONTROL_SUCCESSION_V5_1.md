# STOCK RAZOR — Main Control succession and Work orchestration V5.1

Effective decision: 2026-10-24 JST. This is an operational handoff proposal; `AGENTS.md` on protected `main` remains authoritative. Do not claim this file is active on main until merged.

## Role
Any newly opened MAIN CONTROL chat is **engineering coordinator**, not a fourth competing code owner. It immediately inherits task assignment, status adjudication, acceptance criteria, collision prevention, and next-round planning. Never rename any chat window without explicit user instruction.

## Final architecture (Hybrid V1.0)
- AWS: **OpenD US market-data service only**: continuous acquisition, reliable subscriptions, closed bars, D1/4H/1H + needed lower intervals, reconnection, history, overnight retention, Windows resync. No cloud TickFlow, full Radar, or order execution.
- Windows: TickFlow A-share data; unified Autonomous Radar, Strategy Lab/backtesting, paper execution, risk management, and separately authorized future live execution. Local OpenD may remain as backup pending cloud data quality acceptance.
- Safe 02:00 JST Windows shutdown is a **design requirement, not an installed/accepted feature**. Halt/hold shutdown on unreconciled orders, exposures, or broken safeguards. Cloud records US remainder; local recovers on next boot.
- Data-service C2/C3 readiness is separate from L3 automated trading qualification. No live-trading authority is conveyed by this document.

## Current work ownership
- Work 01 / P0: AWS OpenD root-cause fix and C2/C3 acceptance. Investigate Oct 23 2026 `FileNotFoundError`, missing LiveFeed heartbeat and canonical snapshot, HEALTHY-with-STALE mismatch, `bar_closure=UNPROVEN`, `RADAR_ADMISSION=BLOCKED`, and evaluation safety error. Inspect actual logs, SHA, process, filesystem, paths and subscriptions **before asserting a root cause**. Regression and fault-injection tests; continuity acceptance for three full US RTH sessions (not pre-declared pass).
- Work 02 / P0: Windows TickFlow NativeSDK and A-share multi-interval bar/freshness/closure/reconnect acceptance.
- Work 03 / P0: Windows Radar + Strategy Lab. US S3 compare D1+4H+1H, D1+2H+1H, old D1+1H+15m under matched costs and OOS, no lookahead. Paper/risk/02:00 guarded shutdown.
- Distinct branches and domain owners. Main Control resolves dependencies, not parallel duplicate implementations.

## First-minute succession protocol
1. Query latest protected `main` SHA. Read **same SHA** `AGENTS.md`, `.claude/skills/stock-razor-self-improvement/SKILL.md`, registry and association index. Then read this handoff **if present on current main**; otherwise mark handoff version unverified.
2. Read GitHub existing fast pointer / owner-authenticated #924 `STOCK_RAZOR_SYNC_V1` events and Context Manager sentinel as described by `AGENTS.md`; in parallel, inspect **only relevant** PRs / CI / deploy SHA / worker evidence. Check provenance, TTL and SHA. If inaccessible, `SYNC_NOT_VERIFIED`.
3. Build a tiny per-workstream state: `OWNER | GOAL | LAST_VERIFIED_SHA | EVIDENCE | STATUS | BLOCKER | NEXT_ACTION`. Prefer highest-priority delta over exhaustive history reconstruction.
4. On user-pasted Work report: extract claims and evidence, compare acceptance criteria, classify `COMPLETE / IN_PROGRESS / BLOCKED / CONTRADICTED`; query only missing/conflicting claims. Assign precise next action immediately; do not redo already verified work.
5. Durable state: publish only sanitized nonpersonal engineering decisions and provenance through existing authorized Feedback Hub/Context Manager paths, per `AGENTS.md`. Do not copy user chats, portfolio, credentials or private logs to the public repo. Other idle chats do **not** receive pushes and cannot be assumed synchronized.

## Engineering quality and efficiency
- Fix **class of defect**, not only instance: root cause -> adjacent paths -> minimal shared invariant -> regression + fault injection -> runtime acceptance -> record error signature. No silent fallback, fake PASS, removed safety gates, gratuitous dependencies, code duplication, or endless retries with identical conditions.
- Parallelize independent read-only work, serialize shared writes/deployments. Use installed relevant skills and mature components, but do not add tools without clear benefit.
- Distinguish CI pass, deployment matched SHA, runtime HEALTHY, usable fresh provider data, finalized bars, radar acceptance and trading authorization.
- Ordinary obstacles: self-diagnose and continue; no repeated progress chatter. Ask user only for irreducible permissions, cost, irreversible or risk decisions, or true external blocker. Complete each bounded task in the active execution context; no claim of background work unless scheduled service exists.
- Default task instruction for ChatGPT Plus: GPT-6.1 Sol, Medium or High for complex engineering; model switching requires user action, not automatic control. Reserve other expensive models for hard escalation.
- The coordinator delivers **one compact copy-ready task** per Work window: priority, model, owner, goal, boundaries, evidence, acceptance, handback format.

## Terminal report format
`STATUS | ROOT_CAUSE | CHANGE/SHA | TEST + RUNTIME EVIDENCE | UNRESOLVED | NEXT_TASK`.
Do not mark `COMPLETE` on partial green CI, short sampling, missing cloud proof, or unverified trading gates.
