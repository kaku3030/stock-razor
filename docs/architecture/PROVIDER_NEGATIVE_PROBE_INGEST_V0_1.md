# STOCK RAZOR Negative Provider Probe Ingest V0.1

Status: STACKED IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Translate **sanitized negative runtime evidence** for non-core providers into the
Provider Lifecycle observer.

Initial eligible providers:

- OpenAI
- Anthropic
- Tavily
- Twelve Data
- EODHD
- AWS

Core market-data providers with dedicated runtime contracts
(`moomoo_opend`, `eastmoney`, `tencent`, `alpaca`) are deliberately
rejected by this generic path.

## Negative-only contract

Allowed normalized conditions:

- `AUTH_FAILED`
- `EXPIRED_OR_INVALID`
- `INSUFFICIENT_QUOTA`
- `CREDIT_BALANCE_EXHAUSTED`
- `RATE_LIMITED`
- `PROVIDER_FAILED`

The contract has **no positive condition**. It cannot emit HEALTHY, VALID,
PASS, quota headroom, current balance, freshness, latency, or last-success
evidence.

A future recovery/positive-proof path must use separate provider-specific
evidence.

## Mapping

| Condition | Lifecycle evidence |
| --- | --- |
| AUTH_FAILED | health FAILED + credential_status AUTH_FAILED |
| EXPIRED_OR_INVALID | health EXPIRED + credential_status EXPIRED_OR_INVALID |
| INSUFFICIENT_QUOTA | health EXHAUSTED + billing_status INSUFFICIENT_QUOTA |
| CREDIT_BALANCE_EXHAUSTED | health EXHAUSTED + billing_status CREDIT_BALANCE_EXHAUSTED |
| RATE_LIMITED | health RATE_LIMITED |
| PROVIDER_FAILED | health FAILED |

Every accepted event records `last_failure`, a normalized failure reason,
capability context, and exact provenance.

## Sensitive-data boundary

The payload is not a raw HTTP envelope.

The following keys are rejected if present:

- API key
- Authorization
- headers / request headers
- response body / raw response
- raw error message / message / detail

Only sanitized `error_code`, `error_type`, and optional numeric
`http_status` may be retained.

## Governance separation

The payload must remain:

- `research_only=true`
- `radar_admission=BLOCKED`
- `live_trade=false`

The emitted capability evidence explicitly says:

- `negative_evidence_only=true`
- `data_admission=NOT_EVALUATED`

Provider failure never changes market-data admission by itself. AI/search
provider failure must not stop deterministic Radar core.

## Provenance

Required:

- exact lowercase 40-character `repo_sha`
- timezone-aware `observed_at_utc`
- `runtime_instance_id`
- concrete `probe_source`
- normalized condition

The observer keeps field-level ordering and rejects equal-time conflicts.

## Non-goals

V0.1 does not:

- perform provider network probes;
- fetch account balances or quotas;
- fetch AWS Cost Explorer;
- infer credential recovery;
- authorize fallback;
- send notifications;
- enable paid plans or recharge;
- change Radar or trading admission.

Those remain separate slices.

## Stacked-development note

This implementation is developed above the OpenD/CN/Alpaca runtime-ingest
stack. It is not eligible to merge until prerequisites are merged and its final
diff is rebuilt from current canonical `main` with fresh CI and fresh Code
Owner approval.
