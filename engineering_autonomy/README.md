# Engineering Autonomy V1.1 — bounded coding pilot

Status: CODE IMPLEMENTED ON PR BRANCH; CLOUD / UNATTENDED ACCEPTANCE NOT VERIFIED.

This is a separate Coding Agent lane from the existing V1 audit-only scheduler. It stays
in the same STOCK RAZOR repository, but never modifies trading runtime, AWS, IAM,
Secrets, Radar/Paper admission or LIVE_TRADE. No auto-merge is configured.

## Preflight and gates

- Runs twice hourly (UTC minute 27 and 57) or by manual dispatch, only when
  ENGINEERING_AUTONOMY_CODING_ENABLED is exactly 'true'. The repository setting
  is deliberately not changed by this PR.
- The fixed reviewed task in coding_tasks.json allows edits ONLY to
  tests/test_engineering_autonomy.py. No dynamic Issue text or external prompts.
- Codex Action runs in an ephemeral GitHub-hosted runner with contents:read,
  checkout persist-credentials:false, drop-sudo and a workspace-restricted profile.
  It requires a model credential in the OPENAI_API_KEY GitHub Secret.
- The model's output is an untrusted patch. A fresh, secret-free verification runner
  checks exact changed paths, binary/mode/rename refusal, patch size, pytest success.
- A separate publish runner receives ENGINEERING_AUTONOMY_APP_TOKEN only after
  verification. It opens a Draft PR, never merges. An exact-main SHA check and
  stable branch/PR-history guard prevent stale-base or repeat submissions.
- No credentials are set or read by this PR. The App token must be provisioned with
  least privilege separately and branch protection must be verified.

## Reuse of existing engineering skills

The coding prompt applies the selected Personal Research Hub engineering quality
principles: minimal scope, real regression tests, untrusted input handling and
independent evidence. ChatGPT skills do not automatically run on GitHub runners.

## Acceptance

Implementation alone is not PASS. Require actual model-generated patch from
a scheduled run, independent verification, a Draft PR, passing exact-head CI,
and two consecutive scheduled runs without duplicate execution or unsafe writes.
Missing or invalid credentials, unauthorized files, failed tests, or an unexpected
main SHA must leave the system BLOCKED.

This pilot intentionally makes test-only changes. Extending to code fixes, more
paths, autonomous task selection or merge requires a separate reviewed design.
