# Safe PUBLIC → PRIVATE Source Migration — controlled acceptance stages

STOCK RAZOR GitHub source is **PUBLIC** until every separate infrastructure
acceptance passes. A private ChatGPT plugin is not GitHub repository privacy.

## Existing blockers and preflight meaning

`python scripts/audit_private_repo_deploy_dependencies.py --enforce`
finds known unauthenticated `raw.githubusercontent.com` workflow references
and direct public `git clone` defaults in `ops/aws/install_*.sh`. It is
an **offline static dependency scan, not an authorization engine**.

A future zero-blocker report sets
`static_public_source_dependencies_cleared=true` while deliberately leaving
`private_migration_ready=false` and
`repository_visibility_change_authorized=false`. Authenticated cloud delivery,
restart/recovery/rollback and explicit user approval are separately required.
`--enforce` only checks known static URL patterns; it does not prove every
network dependency has been identified.

Do **not** change repository visibility yet: AWS recovery currently still
depends on unauthenticated public source.

## Stage 1 — manual GitHub artifact only (implemented but not dispatched)

`.github/workflows/private-source-bundle-manual.yml` is `workflow_dispatch`
only; it never deploys to AWS.

- Exact `github.sha` checkout without persisted credentials.
- `git archive` excludes `docs/assets` and the tracked `CLAUDE.md`
  symlink. The unfiltered tree exceeded the 64 MiB verifier cap, so runtime
  functionality needing excluded media must be audited separately.
- Bounded tar size/path/link verification via the existing
  `verify_private_source_tar`.
- A 3-day GitHub Actions artifact with a source commit and SHA256 receipt.
- The self-declared digest in the artifact is **NOT independent proof of
  provenance**. No IAM, SSM, network delivery, service mutation or trading.

Manual workflow execution and artifact readback remain **NOT VERIFIED**.

## Stage 2 — authenticated private delivery (NOT IMPLEMENTED)

Future independently authorized delivery must use a short-lived GitHub OIDC
identity tied to an exact protected source revision, a scoped IAM role,
private **versioned S3**, SSE-KMS, write-once/replay-safe object identity,
auditable cloud receipt, and an independently verifiable signature or
authenticated provenance. Cloud instance role: read-only `GetObject` on
an allowlisted key/version; no personal GitHub token on EC2. Untrusted
`source_commit_sha` fields or the archive's own SHA do not authenticate
a release.

**GitHub plan caveat:** GitHub-hosted artifact attestations for a *private*
repository require GitHub Enterprise Cloud according to GitHub's published
eligibility rules (current docs:
https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).
Do not make a personal/free/private deployment dependent on GitHub hosted
attestations being available after the visibility switch. Design a
plan-compatible independently verifiable signing path instead, and test
it with the actual target account before declaring private-ready.

## Stage 2a — inactive on-host staging (implemented, NOT deployed)

PR #567 added `ops/aws/stage_verified_private_source.py`, which accepts
an **already downloaded** local source tar, an independently trusted digest,
an exact source SHA pin and an existing release root. It reuses the strict
tar verifier, denies duplicates, links, unsafe paths, oversized bundles and
replacements; extracts into an isolated temporary path and stages a
new inactive SHA-named release. This is preparatory code only:

- Does not establish the independent trust chain or fetch S3 objects.
- Does not alter active systemd services or the running code.
- Does not establish that cloud imports, restart, rollback or recovery work.
- Does not provide permission for Paper or real trading.

## Stage 3 — authenticated cloud cutover and recovery (NOT IMPLEMENTED)

- Download the pinned S3 object/version with the instance read role and
  verify cryptographic provenance independently of its bundled receipt.
- Stage in a non-active path; perform import, runtime, endpoint and
  fail-closed gate checks on the exact staged SHA.
- Preserve the running release and test an atomic, reversible service
  cutover in a controlled maintenance window.
- Prove clean restart/reinstall and recovery using only authenticated
  private source; test rollback from actual failure conditions.
- Migrate **all** public-raw workflow source paths and unauthenticated
  installer clones; audit other potential links, not just known patterns.
- Re-run the static scan with `--enforce`, require independent authenticated
  deployment receipts, then seek the user's explicit final GitHub PRIVATE
  permission. Never flip visibility as an unattended inference.

## Trading independence

Source migration never grants market-data freshness, broker account identity
or trading readiness. Required defaults throughout:

`PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
`SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.

No AWS/source deployment or broker API call is performed by this document.
