# OpenD AWS integration stage: dry-run candidate observation only

Existing AWS OpenQuoteContext, FutuK1MStreamingAdapter, and
LiveFeedRuntimeBridge.start remain the **sole real subscription owner**.
This PR adds a pure candidate-plan observer, reusing the runtime bridge's
local acknowledged subscription keys, and includes its output in heartbeat.

The default proposed pool is the existing fixed nine tracked symbols, with
an optional, bounded comma-delimited STOCK_RAZOR_OPEND_PREVIEW_CANDIDATES
environment input for **inspection only** (not subscription). Unknown quota
blocks any proposed addition. No SDK calls are made by the observer and there
is no subscription mutation; no new OpenD connection, feed, or trading path.

Neither bridge ACK nor a PLAN_ONLY result proves remotely active provider
subscriptions, real-time push or provider quota. This is not deployed or
AWS-accepted just because CI passes; promotion remains blocked.

Later AWS verification must confirm exact repo SHA, provider-side actual
subscription list and quota from the same owner, bounded add/remove
integration, warm start, recovery and currentness.
RADAR_ADMISSION=BLOCKED; SOURCE_ARBITER_ADMISSION=BLOCKED;
PAPER_AUTO_READY=NO; LIVE_TRADE=NO.
