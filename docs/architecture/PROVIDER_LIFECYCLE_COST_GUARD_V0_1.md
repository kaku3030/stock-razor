# STOCK RAZOR Provider Lifecycle / Cost Guard V0.1

Status: SELF-SURVIVAL LAYER / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

STOCK RAZOR must not become silently blind because a provider credential expires, quota or credit is exhausted, a rate limit activates, billing changes, or a provider fails.

The Self-Survival Layer must let the system know:

1. what it depends on;
2. when an external dependency is approaching failure;
3. whether a fallback is truly qualified;
4. whether current research output is still trustworthy;
5. when the user must be notified;
6. when the system must degrade or block;
7. when spending requires explicit user approval.

No provider lifecycle feature may authorize live trading or bypass existing data-quality, currentness, timestamp, closure, provenance, Radar-admission, or execution gates.

## Provider Lifecycle Registry

Each runtime provider record includes at least:

- provider_id
- role: PRIMARY / FALLBACK / CROSS_CHECK / AI / SEARCH / INFRA
- market_scope
- credential_status
- credential_expiry
- plan
- quota_total
- quota_used
- quota_remaining
- quota_reset_at
- rate_limit
- billing_status
- auto_recharge_enabled
- last_success
- last_failure
- failure_reason
- latency
- freshness
- coverage
- fallback_provider
- decision_criticality
- daily_cost
- MTD_cost
- projected_monthly_cost
- cost_anomaly
- budget_remaining
- free_period_ends_at

Static registry definitions are not current health evidence.

## Health States

Allowed states:

- HEALTHY
- WARNING
- DEGRADED
- EXHAUSTED
- EXPIRED
- RATE_LIMITED
- FAILED
- UNKNOWN

UNKNOWN must never be promoted to HEALTHY without evidence.

Hard lifecycle evidence may move UNKNOWN directly to a fail-closed state such as EXPIRED or EXHAUSTED.

## Credential Warning Bands

Credential/subscription expiry warning schedule:

- 30d
- 14d
- 7d
- 3d
- 1d
- EXPIRED

## Quota Warning Bands

When quota_total and quota_remaining are known:

- remaining < 25% -> INFO
- remaining < 15% -> WARNING
- remaining < 5% -> CRITICAL
- remaining = 0 -> EXHAUSTED

If an observed usage rate exists, compute projected exhaustion time.

No projection may be fabricated when current quota or burn rate is unknown.

## Cost Guard

Track where evidence exists:

- daily_cost
- MTD_cost
- projected_monthly_cost
- cost_anomaly
- budget_remaining
- free-period end

STOCK RAZOR must never autonomously:

- recharge;
- upgrade a plan;
- enable a paid feature;
- raise a billing limit;
- enable auto recharge.

Any new spend or paid-plan change is:

`USER_APPROVAL_REQUIRED`

The V0.1 contract always reports `auto_spend_permitted=false`.

## Intelligent Fallback

A provider failure is not equivalent to fallback PASS.

Required fallback checks:

1. fallback provider health;
2. freshness;
3. coverage;
4. timestamp/currentness;
5. latency;
6. cross-provider sanity.

Any FAIL or UNKNOWN in a required check blocks the fallback.

Possible results:

- PASS_WITH_FALLBACK / data admission PASS
- DEGRADED
- BLOCKED

A fallback that is itself WARNING or DEGRADED must never be displayed as normal.

## AI Providers Are Ordinary Providers

OpenAI and Anthropic are lifecycle-managed dependencies, not special exceptions.

An AI provider failure must be evaluated by decision criticality.

Example:

```text
Anthropic EXPIRED
-> AI enrichment degraded
-> deterministic Radar core may continue
-> trading admission unchanged
```

An AI failure must not make market-data health look failed when deterministic Radar remains healthy.

## Provider Roles

Initial registry:

| Provider | Role | Scope | Notes |
| --- | --- | --- | --- |
| moomoo OpenD | PRIMARY | US | US primary market-data path |
| Eastmoney | PRIMARY | CN | A-share primary observer path |
| Tencent CN | FALLBACK | CN | Requires independent timestamp/currentness qualification |
| Alpaca | FALLBACK | US | IEX may be used only when qualified; SIP entitlement separate |
| Twelve Data | FALLBACK | US / GLOBAL | Credential/quota/runtime use require evidence |
| EODHD | CROSS_CHECK | CN / GLOBAL | Target CN ETFs have no 1m capability; known 5m/1h only |
| OpenAI | AI | AI | Enrichment / Main-Control API dependency |
| Anthropic | AI | AI | Enrichment dependency |
| Tavily | SEARCH | SEARCH / NEWS | Search enrichment |
| AWS | INFRA | INFRA | Cloud runtime/cost dependency |

## Current Audit Snapshot

Evidence window: 2026-10-07 UTC / 2026-10-08 JST.

| Provider | Provider health / lifecycle | Data admission / capability | Current interpretation |
| --- | --- | --- | --- |
| moomoo OpenD | HEALTHY (observed cloud runtime) | Radar admission still BLOCKED | PRIMARY connected, REALTIME, LV3 evidence, closure proven |
| Eastmoney | DEGRADED / PRIMARY_NOT_SERVING in last CN observation | Not independently admitted | Tencent fallback served the observed CN symbols |
| Tencent CN | provider response available | BLOCKED on currentness in holiday observation | ACTIVE_FALLBACK; BAR_END semantics proven, currentness not proven |
| Alpaca | HEALTHY for IEX credential/read path | IEX only; SIP unavailable; full fallback qualification not yet proven | FALLBACK/CROSS_CHECK only |
| Twelve Data | UNKNOWN runtime health | Free account baseline 800 calls/day; remaining daily quota UNKNOWN | Not currently qualified as trading fallback |
| EODHD | UNKNOWN runtime health | target CN ETF 1m = unavailable; known 5m/1h only | CROSS_CHECK; never 1m fallback for targets |
| OpenAI API | EXHAUSTED on last direct Secure E2E evidence | AI path unavailable until quota/billing recovers and is re-proven | Radar market-data core unaffected |
| Anthropic API | EXPIRED_OR_INVALID for configured local credential | AI enrichment unavailable on that credential | HTTP 401 plus known 2026-10-07 expiry |
| Tavily | UNKNOWN current-period health | September reached 80%; October remaining/reset/burn UNKNOWN | Do not carry September percentage forward |
| AWS | HEALTHY for observed runtime/SSM path | COST health UNKNOWN | Free credit/free-period evidence exists; current MTD burn not yet fetched |

Provider health and data admission are separate dimensions. A HEALTHY provider is not sufficient evidence for Radar admission.

### OpenD

Observed cloud evidence:

- controller CONNECTED
- delivery_mode REALTIME
- bar_closure PROVEN
- fresh LV3 quote-right evidence
- canonical export PASS
- canonical snapshot PASS
- Radar remains BLOCKED
- LIVE_TRADE remains false

Provider/data path is operational, but deployment provenance must be tracked separately from provider health.

### Eastmoney / CN path

Last observed cloud evidence for 159363 / 159611 / 512730 used Tencent with `fallback_from=eastmoney` under the policy `EASTMONEY_PRIMARY_TENCENT_FALLBACK`.

The market-data lane therefore must not display Eastmoney as normal PRIMARY health for that observation. It should expose the primary-not-serving condition and active fallback explicitly.

A-share observer/Radar remains fail-closed on currentness where proof is unavailable.

Holiday/session semantics must not be misclassified as provider failure.

### Alpaca

Observed:

- credential works for IEX stock snapshot
- current IEX data returned successfully
- SIP request rejected as premium_feed_required

Registry must therefore never advertise SIP entitlement unless separately proven.

### EODHD

Support confirmed target CN ETFs do not provide 1m data.

Known supported intervals for the target set are 5m and 1h.

EODHD must never be admitted as a 1m fallback for those targets.

### OpenAI

Observed Secure E2E response:

`insufficient_quota / credit_balance_exhausted`

This is a billing/quota failure, not an MCP or market-data failure.

Known prior event: account was funded with USD 5.50 on 2026-10-03, but later exhausted.

Current exact remaining balance is not inferred.

### Anthropic

Provider notices showed three Anthropic API keys expiring on 2026-10-07 UTC.

A read-only authentication check on the configured local key returned HTTP 401.

Current state is therefore EXPIRED_OR_INVALID for that credential.

The misleading key names containing "moomoo" are still Anthropic keys and must not be treated as OpenD credentials.

### Tavily

Last confirmed quota evidence:

- September 2026 usage reached 80%

October current quota/reset/burn is UNKNOWN without newer account evidence.

The system must not carry September's remaining percentage forward as if it were current.

### Twelve Data

Account creation is known. The welcome notice identifies the current account as a free user with 800 API calls/day.

Current credential validity, quota remaining for the current day, exact rate-limit state, entitlement, and active Radar use are UNKNOWN unless observed.

### AWS

Confirmed:

- initial AWS free-plan credit: USD 100
- free-plan end: 2027-03-30 or earlier if credits are exhausted
- Cost Explorer enabled
- Cost Anomaly Detection enabled
- default anomaly alert: anomalous spend > USD 100 and > 40% above expected

Current MTD cost, remaining credit, and projected monthly burn are UNKNOWN until Cost Explorer evidence is fetched through an authorized read-only path.

Operational infrastructure health and cost health are separate dimensions.

## Provider Alerts

Provider Guard and trading alerts should share a Notification Gateway.

Examples:

```text
PROVIDER WARNING
Tavily quota remaining: 14%
Projected exhaustion: 3.8 days
Radar Core: unaffected
Action: reduce non-critical requests
```

```text
PROVIDER EXPIRED
Anthropic credential expired
AI enrichment: DEGRADED
Radar Core: HEALTHY
Trading Admission: unchanged
```

```text
DATA QUALITY FAILURE
OpenD unavailable
Fallback currentness failed
RADAR_ADMISSION=BLOCKED
New executable trade decisions suspended
```

## Notification Performance

Record separately:

- provider_latency
- canonical_latency
- radar_analysis_latency
- alert_generation_latency
- push_gateway_latency
- delivery_latency where available
- E2E_latency

Track P50 / P95 / P99 plus:

- delivery success
- duplicate rate
- missed alerts
- retry count

ACTION alerts target seconds-level E2E without reducing analysis quality.

## Alert State Machine

Opportunity lifecycle:

```text
WATCH -> SETUP -> ARMED -> TRIGGERED -> COMPLETED / INVALIDATED
```

Only meaningful state transitions should push.

Levels:

- INFO
- SETUP
- ACTION
- RISK
- FAST ALERT

## Delivery Order

Recommended route:

```text
Cloud OpenD Persistent Stream
-> Canonical realtime
-> Incremental 5m/15m/1h
-> Radar realtime state
-> Provider Lifecycle / Cost Guard
-> Alert Engine
-> Low-Latency Push
-> Shadow Alert Validation
-> Paper Trading
-> Paper Auto Execution
-> Live Qualification
-> Live Auto Execution
```

Alerting precedes Paper Trading because alerts themselves generate Shadow-validation evidence.

## Shadow Alert Validation

Track:

- alert precision
- false-positive rate
- missed-opportunity rate
- Trigger -> MFE
- Trigger -> MAE
- invalidated-setup rate
- alert latency
- data-quality failures
- provider failover events

Only validated ACTION-class signals may become Paper Auto Execution candidates.

## UI Health Surface

Simple top-level status:

```text
MARKET DATA
RADAR
AI
NOTIFICATIONS
COST
TRADING
```

Expanded detail should show provider role and health plus:

- SYSTEM HEALTH
- DATA ADMISSION
- RADAR ADMISSION
- TRADING ADMISSION

Provider health must never be used as a shortcut to promote Radar or Trading admission.
