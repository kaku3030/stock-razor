# Provisional Bar and Revision Contract v0.1

## Decision

Market data ingestion and strategy promotion are separate state machines.

A source can be accepted for raw storage, UI display, and research while its bar finality is still unproven. The same source remains blocked from closed-bar event ingress, confirmed Radar signals, Paper fills, and live trading until the closure contract passes.

## State model

| Plane | State | Meaning |
| --- | --- | --- |
| Source acceptance | `ACCEPTED` | Payload passed schema, clock, lineage, and basic integrity checks |
| Bar state | `PROVISIONAL` | Current or vendor-revisable bar; usable for observation only |
| Bar state | `PROVEN` | Closed-bar evidence passed the provider/session/grid checks |
| Bar state | `REVISED` | A later provider payload changed the same bar identity |
| Strategy admission | `BLOCKED` | No confirmed signal or simulated/live order may be created |

The raw payload is append-only. A later payload for the same `provider + symbol + timeframe + bar_end` is a new revision with a stable parent identity. Existing Paper fills are immutable; a correction adds an impact record and triggers feature recomputation.

## Borrowed market-data practice

- Alpaca publishes an `updatedBars` channel because a late trade can change a previously emitted bar's close and volume.
- UTP SIP messages include trade cancel/error and trade correction records linked to the original trade.
- Therefore a first observation is not treated as an immutable final fact by the downstream consumer.

## Hard rejection rules

The ingestion path still rejects or quarantines:

- future-dated source clocks;
- malformed or non-finite OHLCV;
- impossible OHLC relationships;
- provider/source lineage mismatch;
- unrecoverable gaps or duplicate conflicts.

A missing finality attestation alone is not a raw-data rejection. It produces `PROVISIONAL` and keeps strategy admission blocked.

## Required downstream behavior

1. Store the raw payload and provenance.
2. Publish explicit `source_acceptance_status`, `bar_state`, and `strategy_admission`.
3. Promote a prior bar when the next boundary/closure evidence passes.
4. Reconcile post-close vendor revisions by appending a new revision.
5. Recompute affected indicators and mark any prior research result as superseded.
6. Never rewrite a historical Paper fill to make it look as if the corrected value was known at decision time.

This contract does not authorize Radar promotion or any trading path. It removes the ambiguity between “data was received” and “data is safe to trigger a strategy.”
