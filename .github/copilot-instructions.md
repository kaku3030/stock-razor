# Repository Instructions

Canonical source: [`AGENTS.md`](../AGENTS.md).

If any instruction in this file conflicts with `AGENTS.md`, follow `AGENTS.md`.

## Mandatory cross-window self-improvement bootstrap

For every STOCK RAZOR task, read latest `origin/main` `AGENTS.md`,
`.claude/skills/stock-razor-self-improvement/SKILL.md` and
`.claude/skills/stock-razor-self-improvement/failure-registry.json` before
repeating errors or submitting a change. Compare exact SHA and the prior
failure signature; if the same error has the same version/conditions and no
new evidence, STOP rather than retry. The mandatory `ai-governance` gate
checks this shared registry. Follow `AGENTS.md` on any precedence conflict.

## Mandatory incident recall before new probes

At the start of all STOCK RAZOR work, read current-main `AGENTS.md`, the
canonical `.claude/skills/stock-razor-self-improvement/SKILL.md`,
`failure-registry.json`, and `associations.json` at the same SHA.
For a new or recurring symptom, run
`python scripts/self_improvement_recall.py --query "<sanitized description>"`
before rerunning probes or requesting history from the user.
Related symptoms are hypotheses, not confirmed same root cause; use source,
runtime version and test evidence to choose the smallest nonduplicate fix.

## Fast topic-triggered context sync (STOCK RAZOR V1.4)

Before the first task after a project topic like trading, Radar, OpenD, TickFlow,
replay or cloud: read latest GitHub main at one exact SHA, canonical error skill and
registry/associations, and the existing US/CN MCP Context Manager snapshots when
connected. Inspect the latest OWNER-only project sync events in GitHub PR #924.
Use `python scripts/stock_razor_fast_sync.py --route "<sanitized topic>"`
for fast topic classification. Publish substantive new project decisions as
OWNER-authenticated, redacted `STOCK_RAZOR_SYNC_V1` comments only as documented in
`docs/architecture/stock-razor-fast-cross-window-sync.md`; never include private
portfolio holdings or secrets. Missing actual connected reads = SYNC_NOT_VERIFIED.

## Same-turn direct context pointer

On first relevant STOCK RAZOR topic read the stable fast pointer directly via
`https://api.github.com/repos/kaku3030/stock-razor/issues/comments/6269031171`.
Dereference its `latest_discussion_event`, check event timestamp and main SHA,
then corroborate with the existing US/CN Context Manager. When a *new
non-sensitive* project decision is made, append one owner `STOCK_RAZOR_SYNC_V1`
comment in PR #924, update this existing pointer, and direct-read to verify.
No full/private chat mirroring to a PUBLIC repository, no claimed automatic
wakeups or instant delivery across dormant conversations.

## Core Rules

- Respect directory boundaries:
  - Backend: `src/`, `data_provider/`, `api/`, `bot/`
  - Web: `apps/dsa-web/`
  - Desktop: `apps/dsa-desktop/`
  - Deployment/workflows: `scripts/`, `.github/workflows/`, `docker/`
- Do not run `git commit`, `git tag`, or `git push` without explicit user confirmation.
- Before creating/updating PRs, PR review, or issue analysis, refresh the latest code baseline with `git fetch --all --prune`; if the worktree is clean and the current branch can fast-forward, run `git pull --ff-only`. If local changes, conflicts, missing upstream, or non-fast-forward history make that unsafe, do not stash/reset/overwrite local state; analyze against fetched remote refs or record the baseline gap before proceeding.
- PR titles should use `<type>: <change summary>` such as `fix: 修复大盘分析历史记录丢失`; use `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci` where possible, and avoid `[codex]`, `codex`, `autocode`, `copilot`, or other tool/agent source prefixes. Treat this as process guidance and do not use title format mismatches as a hard review blocker.
- Do not hardcode secrets, accounts, ports, model names, absolute environment-specific paths, or environment-specific branches.
- Reuse existing modules, configuration entrypoints, scripts, and tests instead of adding parallel implementations.
- For user-visible behavior changes, CLI/API changes, deployment changes, notification changes, or report-structure changes, update the relevant docs and `docs/CHANGELOG.md`.
- In `docs/CHANGELOG.md`, the `[Unreleased]` section uses a **flat format**: one line per entry formatted as `- [type] description`, where type is one of `新功能`/`改进`/`修复`/`文档`/`测试`/`chore`. **Do not add `### category headers` inside `[Unreleased]`** to minimize merge conflicts in concurrent PRs. A maintainer will reorganize into the full categorized format at release time.
- Use `README.md` only for project positioning, high-level capabilities, quick start, main entrypoints, and sponsorship/cooperation information; avoid updating README unless the change is homepage-level.
- Put detailed module behavior, page interaction, topic configuration, troubleshooting, field contracts, implementation semantics, and edge cases in the appropriate `docs/*.md` file instead of README.
- When config semantics change, sync `.env.example` and assess impact on local runs, Docker, GitHub Actions, API, Web, and Desktop.

## Validation

- Backend changes: prefer `./scripts/ci_gate.sh`; at minimum run `python -m py_compile` on changed Python files and the closest deterministic tests.
- Web changes: run `cd apps/dsa-web && npm ci && npm run lint && npm run build`.
- Desktop changes: build web first, then desktop if feasible.
- Review work should prioritize CI evidence (`gh pr checks`, workflow logs) before re-running local validation.
- AI governance changes: run `python scripts/check_ai_assets.py`.

## AI Asset Governance

- `AGENTS.md` is the single source of truth for repository AI collaboration rules.
- `CLAUDE.md` must remain a symlink to `AGENTS.md`.
- Use `.github/instructions/*.instructions.md` for path-specific guidance.
- Current repository collaboration skills live in `.claude/skills/`; keep them aligned with `AGENTS.md`.
