# US exact-main bounded AWS observation — GitHub Owner trigger V0.1

The existing `.github/workflows/probe-us-cloud-exact.yml` reads only private EC2 US livefeed and Radar heartbeat/canonical snapshot cache for a fixed 30- or 60-second period. It does not call OpenD, the broker, provider subscriptions, or trading execution APIs.

For a PC-independent read-only audit, the repository Owner may comment this **exact literal** on previously merged PR #708:

```
/stock-razor us-exact-cloud read-only
```

The GitHub action checks the literal PR number, pull-request identity, repository owner account, GitHub OWNER association, exact comment body, protected main reference and immutable SHA **before** assuming the *existing* AWS OIDC role. The same main SHA is checked again immediately before SSM dispatch, and any drift fails closed. The comment path has immutable fixed inputs: 30 seconds and nine predefined US securities. Manual workflow_dispatch retains its existing bounded, allowlisted user inputs. The SSM target remains fixed. No IAM, credentials, daemon, order, restart, broker, funding or market-data provider entitlement changes are included.

The response is only `US_EXACT_CLOUD_PROBE_SANITIZED` with finite statuses: deployed worker SHA alignment, sequence progression, timestamp freshness and 15m/60m closure. If the runtime is still on a different SHA than protected main, the workflow intentionally exits with `US_EXACT_CLOUD_RUNTIME_SHA=NOT_VERIFIED`, even when snapshot reads and cadence were healthy. The raw payload and prices must never be printed in public Actions logs.

This is an operational evidence probe and **cannot by itself qualify** D1 (which is absent from the current canonical intraday cache), authenticated ChatGPT MCP protocol, independent broker parity, long off-PC restart recovery, source/Radar admission, or any form of order execution. The project-wide `SOURCE_ARBITER_ADMISSION=BLOCKED`, `RADAR_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO`, and `TRADE_EXECUTION=NO` remain unchanged.

To undo the new GitHub command route, revert the narrowly scoped workflow trigger/guard change; the existing manual-only read-only probe is unchanged in its SSM logic.
