# TickFlow WebSocket zero-callback diagnosis — 2026-10-12

## Actual live-session failure, not market-closure noise

A-share resumed at 13:00 Asia/Shanghai (14:00 JST). The authorized
30-second AWS Tokyo TickFlow Expert Premium test **#38206135825** ran at
2026-10-12 05:00:58 UTC and finished GitHub SUCCESS with:

- REST quotes, 1/5/15/30/60m K-lines and five-level depth all COMPLETED.
- `websocket_quote_smoke=NO_EVENTS_OBSERVED`,
  `quote_callbacks=0`, `quote_events=0`, `error_callbacks=0`,
  `post_initial_update_candidates=0`.
- `connection_call=PASS`, `subscription_call=PASS` indicate **only
  local SDK method returns**, not a completed network handshake, provider
  entitlement, channel ACK or subscribed symbols on the server.
- Independent **read-only** EC2 cache audit #38206279007 returned the
  same source revision and zero-callback evidence, `data_admission=BLOCKED`.
- Existing independent Tencent 15m candles moved to 202610121315,
  although intraday freshness for that returned sample was UNPROVEN.
  Thus lack of TickFlow WS events is a genuine provider/transport
  diagnostic gap, not proof that the China market is still at lunch.

## Added transport diagnostic (no new automatic provider call)

The official sync SDK may return from `stream.connect(block=False)`
while its background worker has already exited. The probe now reads the
known local Python `threading.Thread` state (if exposed via `_thread`)
**after** the bounded wait, **before** `stream.close()`:

- `ALIVE` — background thread was alive; **not** proof of connected WS,
  authenticated stream, channel subscription ACK or live quote.
- `STOPPED` — an observable SDK background thread existed but had
  stopped; can explain silent zero-callback runs.
- `UNOBSERVABLE` — SDK did not expose a normal Python Thread, or
  state was unavailable. Never guess why, or mark it connected.

Only this 3-value enum is permitted through EC2's private sanitized
projection, GitHub Actions, and independently checked existing-cache
readback. Legacy caches without this field remain `REVIEW_ONLY` with
`UNOBSERVABLE` thread state; an explicitly false provenance flag is
rejected. New reports require the explicit
`background_thread_not_provider_connection_proof=true` flag,
and hardcodes `ws_provider_live_qualified=false` regardless of state.
No API key, symbol, raw quote, error text, provider timestamp or latency
distribution is logged publicly.

No provider call, service restart, AWS mutation, new paid subscription,
Paper order or live order occurs in CI/merge. Any next live-session
bounded probe requires explicit opt-in and must not be repeated as a
connection storm. Verify provider **ACK**, quote timestamps, 429
behavior and server-side data rights independently before TickFlow
Source Arbiter promotion.

`PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
`SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.
