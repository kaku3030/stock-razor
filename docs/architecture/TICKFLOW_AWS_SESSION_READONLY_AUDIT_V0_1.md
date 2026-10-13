# TickFlow AWS research audit: weekday market-session checkpoints (V0.1)

Scope: AWS Tokyo *read-only research acceptance only*. This does not change the paid TickFlow collector, canonical data owners, paper status, or trading permission.

Existing workflow: `.github/workflows/audit-cn-tickflow-live-research.yml` runs through GitHub Actions OIDC to a fixed SSM-managed EC2. The workflow verifies exactly two isolated snapshots 65 seconds apart and releases only allowlisted categorical diagnostics to GitHub logs (no OHLC prices, raw dates/timestamps, account details, or secrets).

Schedule: Monday-Friday `02:20 UTC` (10:20 China Standard Time, 11:20 JST) and `06:20 UTC` (14:20 CST, 15:20 JST). Manual `workflow_dispatch` remains available. Schedules are **best effort**: GitHub cron can start late or skip; no exact close-time capture is guaranteed. Mainland holidays may not be observable, and the research gates fail closed rather than infer an open market.

The job checks service activity, private-cache permissions, history, read-only MCP, 15m/60m grid progress, quarantined OHLC quality, source SHA, and independently qualified Tencent price disagreement. A successful Actions job certifies that the audit executed; it **does not** certify a passing real-time source. Before calling the feed live-ready, require actual closed-bar continuity and finality, latency, independent price agreement, and a healthy cloud worker through an entire relevant session.

Admission remains: `SOURCE_ARBITER_ADMISSION=BLOCKED`, `RADAR_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO`, `TRADE_EXECUTION=NO`. Never promote historical-only success. For rollback revert this workflow scheduling change: the existing manual audit remains available.

## Protected-main change-triggered audit

For strictly scoped changes to this research audit script or its GitHub Actions workflow, a `push` on `main` also launches the **same existing, fixed AWS read-only audit**, without an extra paid worker or deployment step. The unchanged exact-`GITHUB_SHA` check, protected-main-only job condition, private SSM target, categorical output and BLOCKED trading/source gates still apply. It is not an unconditional push trigger: unrelated commits do not launch this audit. A successful job is not source admission, live bar finality, or permission to trade.
