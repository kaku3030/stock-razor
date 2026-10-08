# STOCK RAZOR Alpaca Runtime Evidence Ingest V0.1

Status: STACKED IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Translate existing `AlpacaMarketDataAdapter.evidence_events` into Provider
Lifecycle evidence for registry provider `alpaca`.

The adapter already records sanitized runtime lifecycle events including:

- event type and event time;
- owner identity and runtime generation;
- requested feed;
- stream worker/shutdown state;
- sanitized exception type.

It deliberately records subscription acknowledgement and account entitlement as
UNKNOWN. This ingest preserves that boundary.

## Critical entitlement rule

`feed="sip"` means only that SIP was requested. It is **not** proof that the
account is entitled to SIP.

The existing adapter evidence must remain:

- `ack_status=UNKNOWN`;
- `ack_evidence=SDK_registration_return_only`;
- `entitlement_status=UNKNOWN`;
- `entitlement_source=EXTERNAL_ACCOUNT_EVIDENCE_REQUIRED`.

Any adapter event that attempts to promote those values is rejected fail
closed. A future account/entitlement probe must provide independent evidence.

## Lifecycle mapping

Positive local lifecycle events do not prove provider HEALTHY:

- `subscription_registered` -> UNKNOWN;
- `stream_worker_started` -> UNKNOWN;
- intentional stop / successful owner clear -> UNKNOWN.

Negative runtime events may prove scoped degradation:

- subscription registration error -> DEGRADED;
- stream worker error -> DEGRADED;
- shutdown failure / retained owner -> DEGRADED.

One stream-path error does not prove provider-wide FAILED because REST and
other provider paths may still work.

A later successful shutdown clears the current failure state to UNKNOWN while
`last_failure` keeps the historical negative event.

## Data-quality separation

Alpaca Bar/Quote objects contain feed, source timestamps, freshness and
MarketDataHealth. Those are Data Admission facts and are not translated into
Provider Lifecycle health by this V0.1 adapter.

This ingest therefore does not populate provider:

- `last_success` from worker startup;
- `latency_ms`;
- `freshness_ms`;
- credential/entitlement PASS;
- Data Admission;
- Radar Admission;
- execution permission.

## Provenance

The ingest requires an external exact lowercase 40-character `repo_sha`
because current adapter events do not carry repository identity.

Each field retains:

- event time;
- owner identity as runtime ID;
- exact repo SHA;
- runtime generation;
- concrete source `alpaca_adapter_runtime_events`;
- sanitized error type only.

Raw exception messages are not required or persisted by this contract.

## Stacked-development note

This implementation is developed above the CN/OpenD provider-ingest work. It is
not eligible to merge until prerequisites are merged and the final diff is
rebuilt from current canonical `main` with fresh CI and fresh Code Owner
approval.
