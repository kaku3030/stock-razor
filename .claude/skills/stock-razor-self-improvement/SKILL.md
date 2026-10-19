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

## Automatic unknown-failure receipt (V1.2)

1. When the existing Engineering Autonomy 120m executor returns a nonzero code, is timed out, or throws an exception, it must **stop unchanged retries** and persist a sanitized `engineering_autonomy/incidents.json` record atomically. Record only `task_id`, reviewed `kind`, numeric exit classification, exact known/UNKNOWN SHA, workflow run ID, queue revision, environment category and hashed family. **Never record raw stderr, prompt, secret or stack trace.**
2. Existing 120m workflow saves the incident receipt with its resumable checkpoint and uploads a 30-day GitHub Actions artifact for cross-window readers. New failure does not become "root cause known".
3. New CI / Research Radar Tests failures automatically produce a **read-only** artifact under their source run ID, by `.github/workflows/self-improvement-ci-failure-capture.yml`. The capture job sees **only** GitHub job metadata; no provider API or paid model is called and no Github write token permissions are added.
4. Before retrying a similar CI failure, inspect the latest source run's `stock-razor-unknown-ci-<run_id>` artifact, its `failure_family`, then inspect exact-head CI logs separately for real diagnostics. A matching family means **STOP BLIND RETRY / DIAGNOSE**, not a proven identical root cause.
5. Turn verified unknown incidents into permanent `failure-registry.json` entries + regression tests in a protected-main PR. Generic CI-family artifacts expire after 30 days and **do not automatically become permanent knowledge**. Every verification stage must remain explicit: code deployed, watcher triggered, artifact retained, other window read it, corrected root cause.

Example lookup: `gh run list --repo kaku3030/stock-razor --workflow "Capture Unknown CI Failures (Read-Only)" --limit 20`, then `gh run download <capture-run-id> --repo kaku3030/stock-razor --name stock-razor-unknown-ci-<source-run-id>`. GitHub API/connector readers may use the same run artifact metadata.

## Mandatory associative-memory lookup (V1.3)

Every new, unfamiliar or slightly similar technical error MUST trigger associative lookup **before** repeating a prior API probe, raising a duplicate support question, or drafting a new solution:

1. Read the exact current-main `failure-registry.json` **and** `associations.json` (same ref). Cross-check the currently deployed source SHA and past attempt only if evidence exists.
2. Run `python scripts/self_improvement_recall.py --query "<sanitized error or symptom>"` locally, or apply the same indexed mapping using the GitHub connector in ChatGPT. This searches Chinese/English aliases and one-hop related previous failure cases; no paid model/provider call.
3. Read `results[].prior_diagnosis`, `previous_evidence`, `regression_evidence`, `suggested_next_nonduplicate_step` and `related_cases[]` to choose a genuinely different next action. Do **not** infer root cause from related symptoms; historical fixed cases are only evidence for what *might* transfer.
4. On `UNKNOWN_NEW_CASE_NEEDS_RECEIPT`, capture a sanitized new incident using V1.2, investigate and add the validated case plus future useful aliases/links through normal protected-main CI. No asking the user to repeat the same technical history.
5. If the same root cause reappears on unchanged SHA/environment, apply `STOP_DUPLICATE`. For a superficially related but different failure, issue a **root-cause comparison**, not a categorical duplicate stop.

`ai-governance` validates historical association case IDs and mapping structure on every PR. The tool is deterministic and offline: rapid recall, not LLM retraining or proof of production readiness. Read-only help: `docs/architecture/stock-razor-associative-error-memory.md`.

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
