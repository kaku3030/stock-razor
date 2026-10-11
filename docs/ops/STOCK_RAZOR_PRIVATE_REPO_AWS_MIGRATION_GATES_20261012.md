# STOCK RAZOR public → private migration: AWS preflight — 2026-10-12

**Current repository visibility: PUBLIC. Desired direction: PRIVATE.**
This PR does **not** change repository visibility, start any AWS workflow,
move accounts/secrets, deploy providers or invoke trades.

Changing visibility before the existing AWS source transport is replaced
could strand the deployed cloud runtime on its old SHA and break recovery.

## Confirmed blockers on current US LiveFeed deployment

The guard audits five concrete unauthenticated source dependencies:

- GitHub Actions preflight performs `git ls-remote origin` after checkout
  with credentials explicitly not persisted. This needs an authenticated
  read method for a private repository.
- The fixed EC2 host directly downloads both shell scripts from public
  `raw.githubusercontent.com`, pinned by exact commit and SHA256.
  Hash pinning protects integrity but **does not grant private read access**.
- The EC2 installer clones the GitHub source via unauthenticated HTTPS
  and fetches exact commits from the same public repository. Making the
  repository private will break both operations without a separately
  approved private source delivery mechanism.

## New safety boundary

The existing manually invoked, SHA-pinned #601 deployment workflow
explicitly aborts **before AWS credentials and SSM mutations** if GitHub
reports the repository is private:

`PRIVATE_REPO_CLOUD_SOURCE_TRANSPORT_NOT_MIGRATED`

This is safer than attempting a deployment that fails midway while the
existing US LiveFeed service keeps running an older revision.

The offline audit `scripts/audit_private_repo_cloud_readiness.py` reports
only invariant reason codes, no secrets, account IDs, cloud logs or tokens.
Scope is **ONLY** the known US OpenD AWS deployment path, not all
STOCK RAZOR workflows, account permissions, runners, or historical exposure.

A review with no recognized patterns returns `UNKNOWN`, never a positive
migration approval. No GitHub public visibility can be reversed in the sense
of erasing content already obtained or forked by others.

## Safe migration milestones

1. Audit ALL AWS workflows, scheduled cloud jobs, package/source fetches,
   external GitHub Actions, repository collaborators and any embedded secrets
   privately; do not paste those findings into public PRs.
2. Implement a noninteractive **least-privilege authenticated artifact
   delivery** between GitHub Actions and the fixed AWS host. Candidate
   designs include a tightly permissioned short-lived S3 artifact
   transport or a bounded SSM relay; select only after IAM/KMS, artifact
   retention, request charges and upload/download acceptance are reviewed.
   Do NOT place GitHub tokens in SSM command history or logs.
3. Verify exact SHA256-pinned scripts AND immutable application source
   without requiring unauthenticated public GitHub. Verify off-PC
   deployment, restart and recovery in a disposable test environment
   without touching the current running US LiveFeed.
4. Obtain separate operator approval for both visibility change and
   any AWS service restart. Recheck repository accessibility and
   the correct GitHub connector permissions before changing visibility.
5. Only after independently verified private delivery and recovery may the
   public repository be switched to PRIVATE; then retest provider market
   feeds, cache currentness, Radar safety, US SIM evidence and all CI.
   Never use a generic 'private=PASS' marker without evidence.

The exact-account/broker/market protections remain:

`PAPER_AUTO_READY=NO` `RADAR_ADMISSION=BLOCKED`
`SOURCE_ARBITER_ADMISSION=BLOCKED` `LIVE_TRADE=NO`.
