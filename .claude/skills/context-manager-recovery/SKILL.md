---
name: context-manager-recovery
description: Restore Stock Razor engineering context from the read-only Context Manager sentinel before continuing work.
---

# STOCK RAZOR recovery

At the start of a new window, read the repository `AGENTS.md` recovery entry and
query the available legacy read-only MCP surface with
`get_market_analysis(symbols=["__CONTEXT_MANAGER_STATE__"])` or
`get_cn_market_analysis(symbols=["__CONTEXT_MANAGER_STATE__"])`.

Treat the response as evidence only. Preserve per-domain `UNKNOWN`, `EXPIRED`,
`UNVERIFIED`, and `BLOCKED` states; never infer CI, deployment, provider access,
Radar qualification, paper readiness, or trading readiness from transport success.
