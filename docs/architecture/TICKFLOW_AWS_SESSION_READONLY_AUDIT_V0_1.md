# TickFlow AWS research audit: weekday market-session checkpoints (V0.1)

Scope: AWS Tokyo *read-only research acceptance only*. This does not change the paid TickFlow collector, canonical data owners, paper status, or trading permission.

Existing workflow: `.github/workflows/audit-cn-tickflow-live-research.yml` runs through GitHub Actions OIDC to a fixed SSM-managed EC2. Each invocation reads the existing private cache and read-only MCP twice, 65 seconds apart, and releases only allowlisted categorical diagnostics to GitHub logs (no OHLC prices, raw dates/timestamps, account details, or secrets). The audit itself does not make paid TickFlow provider requests or deploy/restart the worker.

Schedule: `0,30 2-7 * * 1-5` UTC, Monday-Friday. This corresponds to 10:00–15:30 China Standard Time and 11:00–16:30 JST, every half hour. Manual `workflow_dispatch` is also available. Schedules are **best effort**: GitHub cron can start late or skip; no exact close-time capture is guaranteed. Mainland holidays may not be observable, and the research gates fail closed rather than infer an open market.

The job checks service activity, private-cache permissions, history, read-only MCP, current-session 5m/15m/60m grid progress, quarantined OHLC quality, source SHA, sequence/freshness, and independently qualified historical price disagreement. It checks the existing collector cache; it does not measure a new provider request. A successful Actions job certifies that the audit executed, not that every data gate passed or that the source is real-time/trading-ready. Before calling the feed live-ready, require actual closed-bar continuity and finality, latency, independent price agreement, and a healthy cloud worker through an entire relevant session.

Admission remains: `SOURCE_ARBITER_ADMISSION=BLOCKED`, `RADAR_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO`, `TRADE_EXECUTION=NO`. Never promote historical-only success. Revert the workflow scheduling change to roll back the recurring schedule; manual audit remains available.

## Protected-main change-triggered audit

For strictly scoped changes to this research audit script or its GitHub Actions workflow, a `push` on `main` also launches the **same existing, fixed AWS read-only audit**, without an extra paid worker or deployment step. The unchanged exact-`GITHUB_SHA` check, protected-main-only job condition, private SSM target, categorical output and BLOCKED trading/source gates still apply. It is not an unconditional push trigger: unrelated commits do not launch this audit. A successful job is not source admission, live bar finality, or permission to trade.
