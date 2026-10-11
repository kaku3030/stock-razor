# Safe PUBLIC → PRIVATE Source Migration (stage 1: offline artifact)

STOCK RAZOR repo is **PUBLIC** until infrastructure migration passes each separate
deployment acceptance. Creating a private plugin does **not** change GitHub
repository visibility. This page is a plan, not evidence of deployment.

## Existing blockers

The source preflight in `scripts/audit_private_repo_deploy_dependencies.py`
detects the current unauthenticated public `raw.githubusercontent.com`
references in AWS GitHub workflows and direct `git clone` defaults in
`ops/aws/install_*.sh`. **Do not change repository visibility yet**: older
cloud reinstall/recovery flows may then fail when the code becomes private.

## Stage 1 — manual GitHub artifact only (implemented)

The workflow `.github/workflows/private-source-bundle-manual.yml` has
`workflow_dispatch` only; **not** scheduled or automatically invoked.

- GitHub Actions checks out the exact `github.sha` with credentials not
  persisted in checkout.
- Builds tracked source as `git archive`, hashes the byte-for-byte tar,
  and calls `verify_private_source_tar` to reject unsafe paths, links,
  duplicates, overlarge bundles and SHA mismatch.
- Uploads to short-retention GitHub Actions artifacts with a bounded
  JSON receipt. Actions artifact is **not** an AWS source artifact.
- Hash printed/packaged alongside its archive is **not** an independent
  authentication root; a recipient must bind hash to separately verified
  GitHub workflow run identity, reviewed immutable commit SHA and trusted
  artifact attestation/signature before any installation.
- No AWS creds, network calls to brokers, production services, IAM or
  infrastructure deployment. No active Paper/real-trade permissions.

## Stage 2 — future signed, private cloud delivery (NOT IMPLEMENTED)

A separately reviewed and explicitly dispatched GitHub CI job may later
acquire AWS short-lived OIDC credentials and publish the exact source
artifact to a **private, versioned S3 bucket**. Must restrict IAM to a
specific bucket key prefix, force SSE-KMS, audit access, and issue signed,
independently authenticated provenance (commit SHA, workflow run identity,
SHA256 and signature). AWS instance role should have **read-only GetObject**
on the immutable version/key. Never copy a personal GitHub token to EC2,
embed signed URLs in logs, or allow public bucket ACLs.

## Stage 3 — future separate staging + cutover (NOT IMPLEMENTED)

- Cloud instance downloads using its least-privileged role and verifies
  provenance **independently**; ensure untrusted archive cannot escape a
  new isolated staging path. Existing `verify_private_source_tar` does
  not extract and explicitly sets `extraction_allowed=False`.
- Stage immutable source, run import tests and health/rollback checks, and
  **only then** switch systemd services atomically. Preserve original
  working release and failure rollback; never replace the live directory
  directly from unauthenticated tar bytes.
- Migrate all workflow public-raw downloads and all AWS installer clone
  dependencies with explicit code review and scoped acceptance.
- Prove a clean independent cloud recovery/reinstall and source revision
  alignment. Rerun static preflight with `--enforce` and verify zero
  known public-only dependencies. These are necessary, not sufficient.
- After old recovery paths are proven to work with private artifacts,
  the user can explicitly authorize the final GitHub visibility change.

## Trading independence

Repo visibility migration **never** promotes trading readiness. Required
defaults remain `PAPER_AUTO_READY=NO`, `RADAR_ADMISSION=BLOCKED`,
`SOURCE_ARBITER_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`; source deployment
and trade authorization are separate decisions.
