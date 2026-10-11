# STOCK RAZOR | Immutable source bundle groundwork — 2026-10-12

## Why this exists

The current repository is PUBLIC, but the operator wants to make the trading
engine PRIVATE. #603 found five known unauthenticated GitHub source transport
dependencies in the existing US AWS deployment. A visibility flip without a
new delivery route would prevent AWS from fetching future source revisions.

This **offline-only** bundle format is a small, independently testable
building block for a future least-privilege, authenticated private artifact
transport. It is **not** the AWS delivery mechanism and does not authorize
changing the repository's visibility or restarting the cloud service.

## Contract

The builder accepts a local Git checkout and an exact 40-hex commit SHA;
it verifies HEAD and uses `git archive` to export **committed source only**,
not dirty worktrees, untracked research patches or local secrets. The result
is an uncompressed tar archive and a small JSON manifest containing:
schema version, exact commit SHA, SHA256 of tar bytes, archive byte count,
entry count and regular file count. These outputs must live outside the
checkout, and existing destination files are never overwritten.

The archive validator bounds total bytes, member sizes and entry counts,
rejects traversal paths, absolute/backslash/control-character names,
symlinks/hard links/other special members, duplicate paths and obvious
credential filenames. No credentials are read, no `aws`/S3/SSM or broker
connections occur, and the checkout's dirty content is never modified.

The consumer-side verifier accepts the manifest + archive AND an
**independently supplied trusted source SHA and archive SHA256**. It
compares the actual archive bytes and manifest, revalidates safe tar
structure, and returns `VERIFIED_OFFLINE_ONLY` at most. A manifest supplied
alongside a malicious bundle is NOT a signature or provenance, so a
self-attested hash is never adequate. We do **not** extract source in this
stage.

Example local, non-cloud research usage:

```bash
python ops/aws/private_source_bundle.py build \
  --repo-root /path/to/trusted/checkout \
  --expected-source-sha <trusted-40-hex-HEAD> \
  --archive /separate/private/scratch/source.tar \
  --manifest /separate/private/scratch/source.json

python ops/aws/private_source_bundle.py verify \
  --archive /separate/private/scratch/source.tar \
  --manifest /separate/private/scratch/source.json \
  --expected-source-sha <trusted-40-hex-SHA> \
  --expected-archive-sha256 <independently-trusted-64-hex-digest>
```

Do not commit, upload or paste production source bundles or real account data
to public GitHub/CI logs, and do not export bundle contents into a third-party
artifact service without a separate security/retention review.

## Remaining P0 gates

1. Independently audit whether full-repository Git archives are small and
   free from committed secrets/license-protected or private account data;
   the current filename denylists are conservative safeguards, **not** a
   complete DLP/scanner or the ultimate packaging allowlist.
2. Design authenticated source delivery from GitHub Actions to the fixed
   AWS host (for example short-lived tightly IAM-scoped S3 with encryption,
   lifecycle expiry and egress cost guards) without leaking tokens into SSM
   command history. Approval and CI tests alone cannot provision IAM.
3. Verify trusted hashes reach the AWS verifier via a channel separate from
   the untrusted artifact, then stage/extract safely into an isolated
   directory before touching any running systemd service. Add roll-forward
   and rollback proofs and ensure service identity/quote owner remains one.
4. Prove real private-repo CI, closed network access, runtime exact SHA,
   off-PC restart/recovery and data currentness; obtain operator approval
   for the visibility flip, AWS restart, and any paid cloud transfer.

`BUILT_OFFLINE_ONLY` / `VERIFIED_OFFLINE_ONLY` NEVER imply deployed,
restarted, bar closure, source admission, SIM ordering or live trading.

`PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
`SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.
