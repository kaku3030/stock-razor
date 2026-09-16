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
| P0 | Unified task ledger and duplicate-work cleanup | Main Control & Trading Desk | This document | `f5ad09409911fc760f39ff1064228610d7bd1fd2` | Read-only inventory of active PRs | IMPLEMENTATION:IN_PROGRESS | CI:PASS (CI run 35067538893; Research Radar Tests run 35067538607) | PENDING | Ledger PR review/merge | Keep this as the sole coordination record; update only on material state change |
| P1-A3 | Radar A3 recorded-fixture continuation | Radar / Quant Research | #145 | merge `f5ad09409911fc760f39ff1064228610d7bd1fd2` | Current main baseline | DESIGN:FROZEN; IMPLEMENTATION:IMPLEMENTED; CI:PASS; REVIEW:ACCEPTED; MAIN:MERGED | Research Radar run 35064562111; repository CI run 35064562308 | ACCEPTED on exact source head | None for merged scope | No duplicate implementation; consume as existing implementation |
| P1-A4 | Radar A4a/A4b current-main continuation | Radar / Quant Research | #146 | main `f5ad09409911fc760f39ff1064228610d7bd1fd2`; head `e45d2670e630d21a4b560dbd5ab9e59a119017c1` | Current main baseline; A3 merged | DESIGN:FROZEN; IMPLEMENTATION:IN_PROGRESS; CI:PASS; REVIEW:PENDING; MAIN:NOT_MERGED | Research Radar run 35067024564 PASSED; repository CI run 35067024566 PASSED | PENDING | Research Radar failure on exact head `a2fb7985`; fix and rerun | Inspect failure, apply minimal patch, rerun both workflows, then request review |
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

## Owner decisions

- USER_PINNED implementation-owner decisions: UNKNOWN in the currently verifiable repository evidence; Main Control must record any explicit decision before changing ownership.
- No merge, PR closure, permission change, or production promotion is authorized by this ledger.

Cross-lane inventory verified: 2026-09-16 UTC
