# Engineering Autonomy V1.1 — controlled code-writing pilot

**Not production autonomous coding until real GitHub-hosted E2E evidence exists.**

This is a deliberately **one-task, one-PR, test-only** bridge from PR #720's
audit-only control plane to a real Coding Agent. It does not replace the V1
scheduler or touch deployments, Radar/Paper admission, or trading gates.

## Architecture and run states

1. Disabled unless repository variable `ENGINEERING_CODING_ENABLED=true`.
2. Read-only preflight rejects non-main refs, validates the one-shot allowlist,
   and checks prior PRs for `AUTO_TASK_ID=autonomy-test-hardening`.
3. A disposable GitHub-hosted job with a read-only token invokes an official
   pinned Codex Action with `OPENAI_API_KEY` through its constrained API proxy.
4. The agent may propose changes **only** to
   `tests/test_engineering_autonomy.py`. All other modifications fail closed.
5. A separate **secretless** job applies the bounded patch and runs tests.
6. A fresh publisher uses the existing `ENGINEERING_AUTONOMY_APP_TOKEN`
   to publish a PR **without executing modified files**, and never auto-merges.
7. An existing PR for this task prevents repeat work; another reviewed task
   recipe is required after the one-shot smoke test.

Do not enable until credentials, branch protection, checks and Actions
permissions have been verified. API usage is paid separately from ChatGPT Plus.

## Acceptance

- `python -m pytest -q tests/test_engineering_coding_gate.py` passes.
- A real scheduled or manually dispatched run edits only the allowed test.
- Secretless verification completes; publisher creates exactly one PR.
- Later scheduled runs skip the completed task.
- Modified binary/oversized/untrusted patches fail before publication.

## Limitations

GitHub scheduled Actions are best-effort, not exact timers. This is an
**executable one-shot pilot, not yet a general continuous engineer**.
Full Engineering Autonomy needs a reviewed task queue, per-run budgets,
retries, independent branch protection and demonstrated end-to-end safety.
