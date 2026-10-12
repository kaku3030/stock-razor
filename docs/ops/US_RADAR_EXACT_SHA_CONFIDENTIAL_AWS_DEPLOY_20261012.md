# US Radar Worker Cloud Deployment Safety Gate — 2026-10-12

**No AWS deployment or Radar restart occurs on PR merge.**

An independently verified US OpenD LiveFeed instance was deployed at
`656c596dae202c90c1961e33f65ac8f87193c387`, but the read-only US Radar
Worker still reports `5e0ef58c2fb748ed6db12b69bb7b7ab40869f316`
for both its runtime and expected data-source revision. Its research
calculations may still run, but stale cross-service provenance **blocks
exact-main acceptance**; never pretend the whole cloud stack is upgraded.

The existing US Radar deploy workflow had three operational gaps:
checkout of mutable main instead of immutable dispatch SHA, unrestricted
manual restart without an explicit acknowledgment, and printing raw AWS
SSM invocation stdout/stderr (potentially entire research/market records)
into public GitHub Actions. Remote install and verify scripts also lacked
SHA256 verification.

The updated workflow:
- Defaults to **inert** until explicitly dispatched from `main` with
  `approve_restart=true` and `expected_main_sha` matching the exact
  dispatch revision and current main HEAD.
- Checks this identity **before** retrieving temporary AWS credentials.
- Aborts before AWS I/O when repository visibility is Private: the
  existing EC2 and GitHub bootstrap still rely on public source transport.
- SHA256-verifies both immutable commit-pinned installer and verifier
  before the remote installer can restart the existing read-only worker.
- Keeps installer/verifier output private in short-lived EC2 files and
  projects **only fixed sanitized** SSM validation markers into Actions
  logs. The existing verifier remains the authority for systemd,
  worker/source revision, sandboxing, research-only and BLOCKED/NO flags.
- Avoids new provider sessions, subscriptions and broker order execution.

**Next operational blockers (not done by this PR)**:
A worker rollout will only pass when the separately deployed US LiveFeed's
*actual* SHA equals the targeted main SHA; a matching GitHub main alone
doesn't meet that condition. The operator must explicitly approve
each controlled service restart and brief feed/worker interruption.
Do NOT dispatch the worker workflow against mismatched source revisions
or in parallel with another cloud upgrade; first verify current
`main`, its corresponding LiveFeed runtime, absence of concurrent
SSM commands, and the original cloud rollback state.

After a supervised worker restart, independently inspect its runtime SHA,
source SHA, real read-only market freshness, bar closure, source poll health,
latency, and non-promotion gates. One heartbeat or sanitized PASS marker
does not equal market currentness or live trading readiness. Quoted user
SIM positions remain legacy/manual and outside strategy-fill accounting.

`PAPER_AUTO_READY=NO`
`RADAR_ADMISSION=BLOCKED`
`SOURCE_ARBITER_ADMISSION=BLOCKED`
`LIVE_TRADE=NO`
