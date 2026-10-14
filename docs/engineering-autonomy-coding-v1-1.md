# Engineering Autonomy V1.1 — manually confirmed test-only coding pilot

**Status:** DeepSeek credential and Aider invocation have worked in cloud E2E runs, but no independent, test-only, auto-generated PR has yet been published successfully. The third E2E after the `--no-gitignore` fix remains **NOT_VERIFIED**.

## One-shot invocation and safety

The GitHub Actions workflow `.github/workflows/engineering-autonomy-coding-v1-1.yml` has **only** `workflow_dispatch`, with a required confirmation input (boolean, default false), and runs only on `main`. It no longer needs a persistent `ENGINEERING_CODING_ENABLED` variable. There is no schedule and therefore no hidden automatic repeat. A user with repository Actions write privileges must intentionally dispatch the single run with `confirm=true`.

1. The preflight validates the strict one-task allowlist and refuses an already-claimed `AUTO_TASK_ID=autonomy-test-hardening` PR.
2. The untrusted generation job runs pinned `aider-chat==0.86.2`, using `DEEPSEEK_API_KEY`, `--file tests/test_engineering_autonomy.py`, `--read .gitignore` and `--no-gitignore`; GitHub write tokens are explicitly unset.
3. Capture rejects any change beyond the single allowlisted test file, as well as malformed/oversized patches.
4. A separate secretless job validates the patch and runs focused regression tests.
5. The publisher obtains a short-lived GitHub App installation token via `actions/create-github-app-token@v2` from `vars.ENGINEERING_AUTONOMY_APP_ID` and `secrets.ENGINEERING_AUTONOMY_APP_PRIVATE_KEY`. It publishes a PR only, **without executing the patch or automatically merging**.

The normal CI and protected-main required checks then run on that generated PR. A generated PR is **never automatically merged**, including during a long-running Engineering Autonomy session.

## Acceptance evidence and current boundary

The earlier E2E runs `38578349405` and `38583786495` reached Aider but failed the fail-closed capture stage after Aider appended to `.gitignore`. PR #747 added `--no-gitignore` to prevent this startup side effect, but the first complete end-to-end run after that change is still pending. **A CI-green workflow patch is not proof that automatic PR publication works.**

For a genuinely unattended 120-minute / multi-hour coding agent, a separate orchestrator must prove multi-cycle task selection, independent verification, finite API billing limits, deadline, retries, safe cancellation and robust checkpoint recovery. PR #748's bounded loop is an offline pytest-task scaffold, not this full functionality.

No schedule, secrets/IAM changes, production deployment, Radar/Paper admission, or real trades are authorized by this change. On any failure, the single manual run stops rather than retrying indefinitely.
