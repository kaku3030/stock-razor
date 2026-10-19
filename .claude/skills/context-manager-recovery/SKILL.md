---
name: context-manager-recovery
description: Restore Stock Razor engineering context from the read-only Context Manager sentinel before continuing work.
---

# STOCK RAZOR recovery

At the start of a new window, read the repository `AGENTS.md` recovery entry and
query the available legacy read-only MCP surface with
`get_market_analysis(symbols=["__CONTEXT_MANAGER_STATE__"])` or
`get_cn_market_analysis(symbols=["__CONTEXT_MANAGER_STATE__"])`.

For a newly seen or previously similar error, also consult current-main
`associations.json` and run `python scripts/self_improvement_recall.py
--query "<sanitized symptom>"` before recommending a duplicate probe.
Use related cases as hypothesis, never a confirmed current failure cause.

Before reporting on a newly mentioned trade / Radar / OpenD / TickFlow topic,
run `python scripts/stock_razor_fast_sync.py --route "<sanitized topic>"`
and inspect the recent OWNER `STOCK_RAZOR_SYNC_V1` GitHub PR #924 events.
The sentinel domains can lag; compare source SHA, event time and GitHub main.
See `AGENTS.md` V1.4, not a new parallel context database.

Treat the response as evidence only. Preserve per-domain `UNKNOWN`, `EXPIRED`,
`UNVERIFIED`, and `BLOCKED` states; never infer CI, deployment, provider access,
Radar qualification, paper readiness, or trading readiness from transport success.

**Mandatory before trusting the sentinel:** fetch current GitHub `main` SHA and at that
same ref read `.claude/skills/stock-razor-self-improvement/SKILL.md` plus its
`failure-registry.json`. Use `python scripts/self_improvement_gate.py --status`
for a fast local summary and run duplicate triage for every repeated failure.
The sentinel is advisory; a stale shared-registry read means
`CROSS_WINDOW_SYNC_NOT_VERIFIED`, not an already-synced claim. See `AGENTS.md`.
