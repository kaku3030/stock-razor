# TickFlow 5m and D1 isolated cloud research extension

This is **research-only**, fixed to 159611.SZ and 518880.SH. The existing
15m/60m read and legacy four-provider-call `build_observation()` tests
remain unchanged unless the isolated AWS worker opts into supplemental frames.

- Opt-in worker sampling: 5m 144 bars, 15m 96 bars, 60m 24 bars, 1d 40
  date-stamped rows, two symbols, maximum eight native SDK calls per poll,
  with SDK retries disabled and no ad-hoc symbol discovery.
- The 5m label grid has exactly 48 completed-bar scheduled *labels* per
  normal Shanghai session. As for 15m, due label does **not** prove finality.
- TickFlow daily native K-line timestamps are provider **date labels** at
  `00:00 Asia/Shanghai` and **NOT exchange bar-end timestamps**.
  Same-day D1 is quarantined until at least 15:02 Shanghai; after this it
  may enter historical research only, with exchange finality still unproven.
  `session_progress` is always **INVALID_REQUEST** for 1d.
- No normalization by price rounding; original vendor floats retained with
  explicit `ohlc_validation`, including the already-reviewed post-close
  historical-only <=1e-5 ETF drift exception.
- Static and live readback paths are via the existing connected
  `get_cn_market_data(symbol="TICKFLOW:159611.SZ", timeframe="5m", limit=48)`
  or `timeframe="1d"`, after the actual cloud worker **and MCP**
  revisions have been independently deployed and verified. The existing
  `TICKFLOW:FAST` route remains 15m+60m only to avoid breaking callers.
- Larger bounded private JSON budget (350KiB decimal bytes) accounts for
  extra periods. Each periodic poll is now eight requests instead of four;
  no change to the existing 60s CN-session / 300s off-hours / 900s
  weekend cadence.

Deployment requires guarded worker rollout **after** current-main MCP
upgrade. Because the previous MCP reader enforces a smaller 150kB cache
limit, observe source SHA and keep historical readback fail closed on
revision mismatch. Do not promote to trade-authorized Source Arbiter
from tests or date-labelled D1.

**Still required on market open:** 5m stream continuity, true exchange
closure/finality, WebSocket reconnection/backfill and actual TickFlow
source admission. No Paper, broker or live order permission is changed.
