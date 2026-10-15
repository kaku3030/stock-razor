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

## Invocation and required external configuration

The workflow is manual-only. It requires a `main`-branch dispatch with an
explicit `confirm=true`; there is no schedule and it never enables auto-merge.

The workflow is fail-closed unless the repository administrator explicitly
configures `ENGINEERING_AUTONOMY_ENABLED=true` and the GitHub App ID/private
key used to mint a short-lived installation token. The token must be allowed
to create a branch and PR. A normal `GITHUB_TOKEN` is not accepted because its
events do not reliably trigger the required PR checks.

The current repository inspection did not verify the presence of that App
credential or a model API. Therefore the implementation can be merged and
tested now, but unattended mutation/merge remains `BLOCKED` until those
runtime prerequisites are independently verified.

## Run evidence

Each successful run writes one JSON record containing only fixed-schema fields:
run id, base SHA, task id, previous run id, status, and reason. Records are
append-only in the PR branch and are retained by the merged history. Secrets,
raw provider output, model prompts, and model responses are never persisted.
The publisher rejects a pre-existing PR for the same run branch before push and
does not merge the generated PR.
