# Engineering Autonomy V1.1 — controlled code-writing pilot

**Not production autonomous coding until real GitHub-hosted E2E evidence exists.**

This is a deliberately **one-task, one-PR, test-only** bridge from PR #720's
audit-only control plane to a real Coding Agent. It does not replace the V1
scheduler or touch deployments, Radar/Paper admission, or trading gates.

## Architecture and run states

1. **Manual-only:** `workflow_dispatch` on `main`, requiring explicit boolean `confirm=true` (default false). There is no schedule or persistent enable flag.
2. Read-only preflight rejects non-main refs, validates the one-shot allowlist,
   and checks prior PRs for `AUTO_TASK_ID=autonomy-test-hardening`.
3. A disposable GitHub-hosted job with no GitHub write token invokes the pinned
   Aider CLI with `DEEPSEEK_API_KEY` and the native DeepSeek provider route.
4. The agent may propose changes **only** to
   `tests/test_engineering_autonomy.py`. All other modifications fail closed.
5. A separate **secretless** job applies the bounded patch and runs tests.
6. A fresh publisher mints a short-lived token using GitHub App ID from
   `vars.ENGINEERING_AUTONOMY_APP_ID` and the private key from
   `secrets.ENGINEERING_AUTONOMY_APP_PRIVATE_KEY`; it publishes a PR
   **without executing modified files**, and never auto-merges.
7. An existing PR for this task prevents repeat work; another reviewed task
   recipe is required after the one-shot smoke test.

Do not manually dispatch with confirm=true until the DeepSeek credential,
GitHub App installation, branch protection, checks and Actions permissions
have been verified. API usage is paid separately from
ChatGPT Plus. The official Codex Action is not used here because its documented
custom endpoint is for the Responses API, while DeepSeek's public compatible
endpoint is Chat Completions-oriented.

## Acceptance

- `python -m pytest -q tests/test_engineering_coding_gate.py` passes.
- A real **manually dispatched** confirmed run edits only the allowed test.
- Secretless verification completes; publisher creates exactly one PR.
- A later manual run skips work after the completed task PR exists.
- Modified binary/oversized/untrusted patches fail before publication.

## Limitations

This workflow has **no recurring schedule**. It is an
**executable one-shot pilot, not yet a general continuous engineer**.
Full Engineering Autonomy needs a reviewed task queue, per-run budgets,
retries, independent branch protection and demonstrated end-to-end safety.

## One-click bounded smoke verification

After the reviewed workflow change is merged and checks pass, open GitHub
Actions → **Engineering Autonomy Coding V1.1 (test-only pilot)** → Run workflow.
Choose branch `main`, check the `confirm` box, and run **once**. A false or
missing confirmation prevents all jobs from starting. Inspect preflight,
DeepSeek/Aider generation, secretless verify, and PR-only publish outcomes.
Do not merge the machine-generated test PR without independent review.
