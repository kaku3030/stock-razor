# 2026-10-12 US K1M 9-symbol correlated gap: deployment-time correlation

Status: **PROBABLE CONTROLLED RESTART / HISTORICAL→LIVE HANDOFF**, **NOT YET
PROVEN BY PRIVATE SYSTEMD JOURNAL**. No direct provider historical correction
has been authorized or run by this change. This is a risk-reduction code gate,
not an assertion of data restoration.

## Independently timestamped evidence

- All nine regular-session US OpenD series (AMD, NVDA, TSLA, AAPL, QQQ, GLDM,
  LITE, AAOI, CIEN) lack the exact K1M bar start **2026-10-12 14:58 UTC** /
  **10:58 EDT**. They skip from 14:57 to 14:59 UTC; confirmed in
  canonical cloud cache by direct read-only MCP and recorded in
  `docs/ops/US_OPEND_COMMON_K1M_GAP_20261013.md`.
- The immediately preceding observed 14:57 minute was stamped
  `HISTORICAL_QUERY` in AMD and GLDM. The subsequent 14:59 minute carried
  no historical-query flag. This is consistent with a warm-start/catch-up
  to live-callback transition.
- The **US LiveFeed deployment Actions run #38266825239 began at
  2026-10-12 14:58:39 UTC**, exactly inside the absent minute.
  The public sanitized runner acknowledged
  `US_OPEND_LIVEFEED_AWS_DEPLOYMENT=PASS` at **14:59:21 UTC**, which included
  a SHA-pinned installer that explicitly issues
  `systemctl restart stock-razor-us-livefeed.service`.
  This proves the *deployment/restart window* overlapped the missing
  minute, but GitHub logs do not reveal the **precise** EC2 systemd restart
  timestamp or whether provider delivered that K1M callback.
- The US Radar Worker deployment #38267115978 started later at 15:00:55
  UTC. It cannot be the initial 14:58 upstream LiveFeed interruption.
- Cloud heartbeat `CONNECTED/HEALTHY`, current quote-right `PASS/LV3`,
  and hundreds of thousands of later callbacks do not retroactively prove
  the 14:58 bar. The affected AMD 14:45–15:00 15m closed bucket remains
  **incomplete with MISSING_BAR**. No affected 15m/60m or market-source
  admission is authorized.

## Prevent repeated RTH interruption

Protected GitHub workflow preflights **before AWS OIDC**, and its exact-SHA
EC2 installer independently checks **before git checkout** and **again
immediately before systemd restart**. All checks veto *every US weekday*
09:00–16:30 **America/New_York** (includes conservative preopen/
post-close buffers, automatically respects DST). Lack of clock/tz proof
fails closed; no operator override exists in this path.

This intentionally favors data continuity over urgent discretionary
restarts. Emergency incident operations need independent reviewed procedures,
not weakening this regular installer. The EC2 installer change has **no
effect until a separately approved off-window SHA-pinned deployment**.

## Remaining causal proof and recovery

1. Privately compare EC2
   `journalctl -u stock-razor-us-livefeed.service` / systemd stop-start
   monotonic times for **14:57–15:01 UTC** with OpenD transport reconnect,
   callback arrival, queue-loss, and writer/recovery counters. Print only
   fixed enums/times to public GitHub, never raw payloads or positions.
2. If an exact provider K1M historical request is approved and within
   entitlement/price quotas, query this **specific 14:58** interval.
   Distinguish an independently returned provider bar from mere clock
   stitching. A present K1M provider bar would support a local restart/
   ingestion hole; provider absence would suggest a different cause.
3. Pass any provider-verified missing bar through existing source-attested
   warm-start/history-reconciliation and replay closed grids. **Never**
   insert made-up OHLCV, assume zero volume, or mutate canonical cache
   directly.
4. Independently verify native OpenD K5M volume/turnover parity and
   multi-symbol 15m/60m closure before reconsidering source qualification.

Always `RADAR_ADMISSION=BLOCKED` `SOURCE_ARBITER_ADMISSION=BLOCKED`
`PAPER_AUTO_READY=NO` `LIVE_TRADE=NO` `TRADE_EXECUTION=NO`.
TickFlow and isolated internal Paper lanes remain separate.
