# Engineering Autonomy V1

This workflow is a bounded GitHub Actions control plane for low-risk engineering
work. It is deliberately not a general-purpose coding agent.

## Safety contract

- The scheduler reads only `docs/engineering-autonomy-tasks.json` and the
  previous sanitized records under `docs/engineering-autonomy/runs/`.
- Task definitions are a positive allowlist. They contain no shell commands,
  model prompts, URLs, credentials, or arbitrary file paths.
- V1 has one task recipe: create a sanitized run record. It does not modify
  production code, deploy, restart services, change IAM/secrets, admit Radar or
  Paper, or place orders.
- A future code-changing recipe must be added as a separately reviewed task
  definition with its own focused tests and path/command allowlist.
- Untrusted PR, issue, commit, and model text is not used as instructions.
- Under V5.1 the workflow ends after creating the PR. It does not enable
  Auto-Merge or merge its own output. Required CI success, an enabled scheduler
  and a configured App token do not authorize merge or deployment.
- System ownership and acceptance evidence are indexed in
  [the V5.1 matrix](architecture/v5-system-acceptance.md).

## Required external configuration

The workflow is fail-closed unless the repository administrator explicitly
configures `ENGINEERING_AUTONOMY_ENABLED=true`. It also requires a GitHub App
token path capable of creating a branch and PR. A normal `GITHUB_TOKEN` is not
accepted because its events do not reliably trigger the required PR checks.

The current repository inspection did not verify the presence of that App
credential or a model API. Therefore the implementation can be merged and
tested offline, but unattended branch/PR creation remains `NOT_VERIFIED` until
those runtime prerequisites are independently verified. Self-merge and
production deployment remain blocked without separate authorization.

## Run evidence

Each successful run writes one JSON record containing only fixed-schema fields:
run id, base SHA, task id, previous run id, status, and reason. Records are
append-only in the PR branch and are retained by the merged history. Secrets,
raw provider output, model prompts, and model responses are never persisted.
