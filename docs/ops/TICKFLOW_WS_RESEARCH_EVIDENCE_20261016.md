# TickFlow WebSocket research evidence

The official TickFlow Python SDK documents the unified `/v1/ws/stream` endpoint
with `quotes` and `depth` channels. The CN research worker now has an explicit,
opt-in `quotes` observer that uses `TickFlow.stream`, attaches sanitized callbacks,
and publishes bounded counters into the existing private research cache.

## Contract

- The feature is disabled unless `TICKFLOW_RESEARCH_WS_ENABLED=true`.
- The worker uses the already-installed isolated `tickflow[realtime]` dependency.
- Only the approved ETF symbols are subscribed.
- The observer records subscription/connection method calls, not provider ACKs.
- The first quote for a symbol is a cached-snapshot candidate.
- Later provider-timestamp advances are update candidates, not continuity or SLA proof.
- Raw quotes, prices, timestamps, error text, URLs, and credentials never enter the public projection.
- `continuous_feed_qualified=false`, `bar_finality=NOT_VERIFIED`, and all admission/trading gates remain closed.

The observer is evidence plumbing for the existing research cache. It is not the
Radar's production market-data owner and does not replace the K-line maturity or
bar-stability audits. TickFlow's documented WebSocket channels are quote/depth
channels; they do not provide an authenticated K-line finality event.

## Verification boundary

Presence of `websocket_evidence` in a valid cache proves only that the private
observer produced a sanitized observation envelope. Missing, stale, malformed,
or non-allowlisted evidence is rejected or remains unknown. Continuous use still
requires an explicitly authorized cloud run with the current source SHA and the
provider's actual WebSocket entitlement.
