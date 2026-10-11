# US OpenD LiveFeed: guarded manual cloud deployment (2026-10-12)

**This change modifies the workflow for a future explicitly authorized
deployment. Merely merging the PR does NOT deploy to AWS.**

## Reason for hardening

The original `deploy-us-opend-livefeed.yml` checked out mutable `main`,
downloaded shell scripts with `curl` without verifying their digest
and printed the entire AWS SSM invocation response, including remote stdout
and stderr. It performed a service restart when manually dispatched, without
requiring an explicit acknowledgment of the restart.

The guarded workflow now defaults to an inert skipped job. A user must
manually dispatch it **from main**, check the approval boolean and enter
the exact 40-character main SHA. The job checks that immutable checkout
matches both the dispatch SHA and current main HEAD. If main changes
between dispatch and execution, the job fails before AWS mutation.

The runner computes SHA-256 hashes for both pinned installer and verifier
from the reviewed checkout. The fixed EC2 instance downloads each script
at that immutable commit, validates **both hashes before starting the
installer**, and only then runs the existing service installer. That
installer can restart an existing, read-only systemd service, so this is
an explicitly state-changing infrastructure operation even though no
broker orders or subscriptions are manually sent by the workflow.

## Log privacy and acceptance

Remote installer and verifier stdout/stderr are saved to a private temporary
directory on the target (mode 0700) and erased at the end. The verifier
performs detailed runtime, historical warm start, snapshot, exact SHA and
BLOCKED/NO trading safety validation. Only four fixed sanitized markers
are returned over SSM and printed in GitHub Actions. On failure the runner
never prints raw SSM output or sensitive internal broker/market records.

The SSM status must be Success and all four markers must match exactly.
This establishes **deployment script acceptance**, not independently
verified live market quote currentness, true bar closure, automated Radar
admission, or broker fill evidence. Those remain separate gates.

## Operating procedure (only when separately authorized)

1. Confirm current GitHub main SHA, verified cloud readiness, existing
   OpenD quote owner and available quota. Agree to a planned **service
   restart** and possible temporary US cloud feed interruption.
2. In GitHub Actions, select **Deploy Read-Only US OpenD LiveFeed**, branch
   `main`. Enter that exact SHA as `expected_main_sha` and explicitly
   select `approve_restart=true`. Never paste account secrets or IDs.
3. Verify workflow success, deployed runtime SHA via independent read-only
   `Probe US Cloud Exact Main` (manual, once), one existing quote-context
   owner, snapshot age/closure data, and that all four admission gates stay
   BLOCKED/NO.
4. If preflight, install, restart or verification fails, do **not**
   re-trigger blindly. Read sanitized AWS status, review the existing
   service health, and coordinate a safe rollback/recovery separately.
   This PR does not pretend to guarantee transactional rollback.
5. Use a separate approved deployment for any provider subscription change;
   this workflow does not authorize TickFlow paid requests or Paper orders.

## Explicit non-admissions

Merging this PR is **not a deployment**, and neither these CI tests nor
the SHA/SSM envelope demonstrate current live data qualification.

PAPER_AUTO_READY=NO
RADAR_ADMISSION=BLOCKED
SOURCE_ARBITER_ADMISSION=BLOCKED
LIVE_TRADE=NO
