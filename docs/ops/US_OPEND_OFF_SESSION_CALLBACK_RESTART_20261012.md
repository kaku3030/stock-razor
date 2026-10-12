# US OpenD 20s callback gate — confirmed regular session only (2026-10-12)

**Pre-deployment P0 discovery:** At the current Japan morning time, the US
equity market is outside its regular session. The existing AWS installer
starts a US regular-session K_1M feed and raises
`US_OPEND_STARTUP_CALLBACK_STARVATION` if no data callback arrives within
20 seconds, *without checking the exchange market state*. This can cause
restarting an otherwise healthy cloud service in a closed session. Its
separate acceptance verifier also previously required `event_count > 0`
unconditionally.

The fix constrains the runtime restart condition to a **positively
confirmed regular US session** (valid OpenD global-state reply and
`cache_session == "regular"`). Missing data for 20 seconds remains a
hard failure when that evidence exists. After-hours, premarket, overnight,
closed and unknown states do not trigger *RTH callback starvation*
restarts; this is not treated as fresh data evidence or permission to
trade.

The existing AWS verifier accepts a zero callback count **only** if
OpenD global market-state evidence is PASS and the session maps to
`closed`, `premarket`, `afterhours`, or `overnight`. Unknown
market state and regular-session no-data still fail acceptance. Exact
runtime SHA, three-session historical warm start, daily history, canonical
snapshot, subscription observer, data/closure and BLOCKED/NO trading
checks remain mandatory. Closed-session acceptance does **not** assert
fresh realtime quote delivery or prove next market-open recovery.

Synthetic tests run the exact embedded runtime AST condition and exact
embedded acceptance predicate over both regular-session failure and
off-session scenarios.

**This is code and CI only.** No deployment or restart is performed by
merge. For the approved controlled cloud deploy, use only the existing
manual #601 safeguarded GitHub Actions workflow on latest main with
explicit restart consent and expected exact main SHA. Confirm the fixed
AWS host, existing one quote owner, command history and rollback readiness
separately; do not reuse a stale SHA or claim closed-session K-line
freshness. Independent exact-main cloud probe and first active-session
recovery observation remain REQUIRED.

`PAPER_AUTO_READY=NO`
`RADAR_ADMISSION=BLOCKED`
`SOURCE_ARBITER_ADMISSION=BLOCKED`
`LIVE_TRADE=NO`
