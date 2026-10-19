---
name: stock-razor-self-improvement
description: Mandatory fail-closed cross-window STOCK RAZOR engineering memory; read newest main and known failure signatures before touching code, market data, Radar, cloud, or strategy research.
---

# STOCK RAZOR | Self-Improvement V1.0 (project skill)

**Authority:** `AGENTS.md` at `kaku3030/stock-razor` **current `main`**, never a recalled chat answer, unmerged PR or old local checkout.

## Must-run at the beginning of EVERY STOCK RAZOR working window / handoff

1. Read **current** GitHub `main` full commit SHA, `AGENTS.md`, this `SKILL.md` and `failure-registry.json` **from the same commit**. A cached copy older than current main is non-authoritative. Do not silently reuse a previous answer.
2. Read Context Manager `__CONTEXT_MANAGER_STATE__` via connected STOCK RAZOR MCP when available; validate timestamp and provenance separately. This sentinel is **supporting evidence**, not a substitute for current main.
3. Inspect related PRs/CI, exact deployment SHA and current provider state as applicable. Select the smallest known failure signature. For known failures, **first consult the recorded mandatory action and previous evidence**, not another unbounded probe.
4. Start work. Before every meaningful new retry, failure reoccurrence, code merge, live-session validation, or status report, check the latest current-main registry revision and the target subsystem error signature. A different chat window is NOT evidence the failure disappeared.
5. If current task reveals a new, verified root cause or fixes an existing one, modify this single registry through a normal GitHub PR, attach exact SHA and deterministic regression tests, and let protected main CI validate before merge. Avoid modifying registry solely to declare victory.
6. Refresh main/registry on every user '继续' request when the last window check predates a relevant merge, failure, deployment or alert. For idle work, a fresh GitHub read is preferable to guessing from memory.

## Repeat-error gate (operational rule)

Identify `failure_id` by known signature tokens (all tokens must appear in canonical diagnosis/log excerpt). Classify:
- `STOP_DUPLICATE`: same failure + same code SHA + same environment/probe args + no new evidence. Do not make the same paid/provider/network/CI retry again.
- `DIAGNOSE_OR_PATCH`: first occurrence, code SHA or configuration differs, or new evidence identifies another root cause. State what changed.
- `UNKNOWN`: no registry match, or source cannot be authenticated. Do not mark PASS.

Run `python scripts/self_improvement_gate.py --signature "<sanitized error excerpt>" --sha <actual_sha> --previous-sha <last_failure_sha>` to receive categorical machine output. Use `--check-registry` in CI and `--status` for a fast human/machine digest. This helper **does not** know secret environment variables, provider-side contract changes or missing remote logs; operators must assess environment change separately. Don't use `--previous-sha` without a verified matching prior failure.

## One canonical state, three layers

- **Rules:** `AGENTS.md` + this skill. Global policy for project agents and newly started windows.
- **Failure cases:** `failure-registry.json` + evidence links. Stable identifiers, signature tokens, owner, failure diagnosis, next action and regression evidence; edits immediately visible via GitHub current-main reads.
- **Execution evidence:** current GitHub PR/CI, Context Manager/Feedback Hub when provenance-valid, deployment and provider telemetry. Never re-label unknown with a successful transport.

**Availability boundary:** These files are shared instantly *for a window that fetches current GitHub main*. Existing ChatGPT conversations cannot be silently pushed new instructions while inactive, and ChatGPT model weights do not change. Do not claim that old sessions auto-reloaded or that independent chats are automatically subscribed. Windows without GitHub access must say `SYNC_NOT_VERIFIED` and cannot claim cross-window rule compliance.

## Fast path (V1.1)

- For local/CI startup: `python scripts/self_improvement_gate.py --brief` emits one bounded JSON packet (<900 bytes) with unresolved P0 IDs, failure counts, registry revision, and explicit cross-chat-sync `NOT_VERIFIED`.
- Autonomous workflows `engineering-autonomy-120m.yml` and `engineering-autonomy-coding-v1-1.yml` require exact current GitHub main and the registry check **before** reviewed engineering checks or any paid test requests. Divergent code SHA blocks the task; this check does not certify the provider or trading.
- User command `继续 / 推进 / 如何`: fetch exact current main + relevant registry errors + current evidence; prioritize executing one smallest high-value nonduplicate fix rather than repeatedly writing plans. Attempt parallel read-only evidence-gathering only when independent. Report measured latency when available, not made-up speed metrics.
- The short brief accelerates *local/Codex/CI* startup. ChatGPT windows still must retrieve the latest GitHub main and same-ref source files using connected GitHub (no automatic cross-chat broadcast).

## Required work product (show only real outcomes)

`main_sha`, `registry_revision`, `failure_id(s)`, `change_since_last_attempt`, `local_test`, `exact_head_ci`, `deployed_sha`, `provider_freshness_and_finality`, `notification_receipt`, `gate_status`, `next_non_duplicate_step`.

- No percentage-only self-improvement claims, no "everyone synced" without a cross-window fetch probe.
- No automatic trading, purchase, paid model/provider access, IAM/secret mutation or source arbitration relaxation on the strength of this skill.
- Priority: Local Windows P0; during US regular market time, cloud OpenD validation temporarily tops the queue; cloud TickFlow last until earlier levels stabilize.
- Every solved root cause MUST have a reproducible regression that initially fails or an explicit `NOT_VERIFIED` exception pending test. Fail closed when the exception matters to live trading.

## Quick window bootstrap (GitHub authenticated)

```
git fetch origin main
git rev-parse origin/main
cat AGENTS.md
cat .claude/skills/stock-razor-self-improvement/SKILL.md
python scripts/self_improvement_gate.py --status
python scripts/self_improvement_gate.py --check-registry
```

For ChatGPT cloud-only sessions, read the same four files using the connected GitHub tool, not a local checkout.
