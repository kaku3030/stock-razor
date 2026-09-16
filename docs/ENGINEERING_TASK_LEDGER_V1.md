# STOCK RAZOR Unified Engineering Task Ledger V1.0

Effective baseline: 2026-09-16

This ledger is the single coordination record for active STOCK RAZOR engineering work. It does not grant merge, production, trading, or permission authority. Every status is bound to the latest verified exact head.

## Status dimensions

Use these dimensions separately:

- DESIGN: FROZEN / IN_PROGRESS / UNKNOWN
- IMPLEMENTATION: IMPLEMENTED / IN_PROGRESS / UNKNOWN
- CI: PASS / FAIL / IN_PROGRESS / UNKNOWN
- REVIEW: ACCEPTED / PENDING / UNKNOWN
- MAIN INTEGRATION: MERGED / NOT_MERGED / UNKNOWN
- PRODUCTION PROMOTION: NOT_AUTHORIZED / FROZEN / PROMOTED

## Active task ledger

| Task ID | Task Name | Production Owner | Canonical PR | Main SHA / Exact Head | Dependencies | Status | CI Evidence | Review | Blocker | Next Action |
|---|---|---|---|---|---|---|---|---|---|---|
| P0 | Unified task ledger and duplicate-work cleanup | Main Control & Trading Desk | This document | `30a6391f80649e0be28ed80dbfe4a818309636e8` | Read-only inventory of active PRs | IMPLEMENTATION:IN_PROGRESS | CI:PASS (CI run 35067538893; Research Radar Tests run 35067538607) | PENDING | Ledger PR review/merge | Keep this as the sole coordination record; update only on material state change |
| P1-A3 | Radar A3 recorded-fixture continuation | Radar / Quant Research | #145 | merge `f5ad09409911fc760f39ff1064228610d7bd1fd2` | Current main baseline | DESIGN:FROZEN; IMPLEMENTATION:IMPLEMENTED; CI:PASS; REVIEW:ACCEPTED; MAIN:MERGED | Research Radar run 35064562111; repository CI run 35064562308 | ACCEPTED on exact source head | None for merged scope | No duplicate implementation; consume as existing implementation |
| P1-A4 | Radar A4a/A4b current-main continuation | Radar / Quant Research | #146 | merge `cc79ce3a9733895160677649f8a43722ed029b85`; current main `30a6391f80649e0be28ed80dbfe4a818309636e8` | A3 merged; current main advanced via #129 after #146 | DESIGN:FROZEN; IMPLEMENTATION:IMPLEMENTED; CI:PASS; REVIEW:ACCEPTED; MAIN:MERGED; PRODUCTION PROMOTION:NOT_AUTHORIZED | Research Radar run 35079233687 PASSED; repository CI run 35079233747 PASSED | shucai30 APPROVED exact source head `3de0855b` | None for merged research scope; production promotion remains closed | Main-integration audit on merged tree; retain research-only boundary |
| P2 | AI Monitor LiveFeed convergence | AI Monitor | UNKNOWN | main `f5ad09409911fc760f39ff1064228610d7bd1fd2` | Provider Worker, Currentness, Consumer Ownership inventory | DESIGN:UNKNOWN; IMPLEMENTATION:UNKNOWN; CI:UNKNOWN; REVIEW:UNKNOWN; MAIN:UNKNOWN | UNKNOWN | UNKNOWN | Unique implementation version not yet identified | Read-only inventory; identify one canonical implementation and duplicate PRs |
| P3 | Quant Research Machine V0.1 real-data validation | Radar / Quant Research | #126 (merged) | main `f5ad09409911fc760f39ff1064228610d7bd1fd2` | Baostock/AkShare/yfinance capture artifact | DESIGN:FROZEN; IMPLEMENTATION:IMPLEMENTED; CI:PASS; REVIEW:ACCEPTED; MAIN:MERGED; PRODUCTION PROMOTION:NOT_AUTHORIZED | Merge CI passed; real-data artifact not yet verified | ACCEPTED | First trusted real-data artifact pending | Inspect first capture artifact, PIT/anti-leak, OOS and cost-delay evidence |
| P4 | Minimal Core and governance cleanup | Main Control & Trading Desk | UNKNOWN | main `f5ad09409911fc760f39ff1064228610d7bd1fd2` | P0/P1/P2/P3 blockers | DESIGN:BACKLOG; IMPLEMENTATION:NOT_STARTED; PRODUCTION PROMOTION:FROZEN | UNKNOWN | UNKNOWN | No blocking issue currently identified | Do not open new implementation scope unless it unblocks an active task |

## Ownership rules

- Main Control coordinates priority, dependencies, and integration.
- AI Monitor owns Provider Worker, LiveFeed, Currentness, Portfolio Runtime Truth, continuity/restart/reconciliation, notification, AI invocation, and Shadow/LIVE runtime.
- Radar / Quant Research owns Candidate Discovery, RS, Capital Persistence, Lifecycle, Replay/OOS, Strategy Lab, Quant Research Machine, Model Evaluation, and research scoring.
- Harvest supplies evidence and reuse analysis; Control Tower performs independent review.
- A historical approval or CI result never transfers to a new exact head.
- Research-only results never grant production authority.
- Never-Seen Holdout remains protected and cannot be consumed by this ledger.

## Cross-lane synchronized inventory

This section records read-only evidence only; it does not select a new implementation owner or authorize merge.

| Lane / Slice | Canonical PR | Exact Head | CI | Review | Main / Promotion | Decision |
|---|---:|---|---|---|---|---|
| AI Monitor Active Watch Universe | #129 | `cca7d93562d2b4d6386b6221639b2292e4b8723c` | CI + Radar PASS (35065694208 / 35065694195) | shucai30 APPROVED | NOT_MERGED / FROZEN | Exact-head evidence exists; base is older than current main, so rebase/sync required before landing |
| AI Monitor consumer-intent delta | #130 | `06f3e0de9886ed2e2e19ce9e04f47cef532f954a` | CI + Radar PASS (35046368405 / 35046368412) | No independent approval recorded | NOT_MERGED / FROZEN | Stacked on #129; do not merge independently before dependency decision |
| LiveFeed consumer ownership | #135 | `9b07d2f86e40b0ed7eb0394dc0097d484ebfd889` | CI + Radar PASS (35046983471 / 35046983445) | Commented audit; no approval recorded | NOT_MERGED / FROZEN | Prerequisite for runtime binding; #138 is the later ingress slice |
| AI Monitor consumer-bound ingress | #138 | `8f8afa41aa262a16a9969a822e128cdff0293a25` | CI + Radar PASS (35059454868 / 35059454831) | shucai30 APPROVED | NOT_MERGED / FROZEN | Candidate implementation; exact-head merge/base review still required |
| AI Monitor USER_PINNED persistence | #133 | `0e3970c842a936c36cd4e3e096f81000db5ed09f` | Radar PASS; CI FAIL (35046487146 / 35046487179) | None | NOT_MERGED / FROZEN | Blocked; separate from #131 until owner deduplication resolves |
| Shadow observation assembly (research) | #144 | `f96b9eb7e048be80a6f8cc5557bfaef2cbb9b384` | CI + Radar PASS (35065176405 / 35065176407) | shucai30 APPROVED | NOT_MERGED / FROZEN | Research/Shadow seam only; never production runtime authority |
| Provider Read R2-S1/R2-S2 | #104 / #112 | `e07107b4` / `cd973303` | Historical/stale relative to current main | Pending or stale | NOT_MERGED / FROZEN | Requires current-main integration owner decision; no direct promotion |

## Owner decisions

- USER_PINNED implementation-owner decisions: UNKNOWN in the currently verifiable repository evidence; Main Control must record any explicit decision before changing ownership.
- No merge, PR closure, permission change, or production promotion is authorized by this ledger.

Cross-lane inventory verified: 2026-09-16 UTC
