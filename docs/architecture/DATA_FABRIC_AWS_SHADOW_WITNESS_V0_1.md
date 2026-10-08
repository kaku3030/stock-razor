# AWS US/CN Data Fabric Source Arbiter Shadow Witness V0.1

**Status: read-only AWS operational bridge. Data/Source/Radar admission remains blocked.**

Run the manual GitHub Actions workflow
`.github/workflows/audit-data-fabric-cloud-source-shadow.yml` after the
Read-Only MCP checkout on AWS Tokyo is deployed to the exact current `main`.
The workflow uses short-lived GitHub OIDC credentials, existing Systems
Manager access and the **existing** EC2 instance. It does not depend on the
user's desktop or create new paid resources.

The cloud probe `scripts/probe_cloud_source_arbiter_shadow.py` reads only
existing local, already-sanitized runtime readers:

- US: OpenD health, Canonical snapshot status and 15m counts for
  `US.AMD` and `US.NVDA`;
- CN: current 15m observer cache and provider provenance for `159611`
  and `518880` (Tencent or Eastmoney only).

For each stream the shared `data_fabric_source_arbiter_policy` receives a
bounded Candidate and prints the exact missing qualifications. It is a
`BLOCKED` shadow witness: all independently unverified gates (network
reachability, exchange entitlement, clock-aligned freshness, source
progression, continuity, OHLCV correctness/completeness, cross-source
confirmation) remain `UNKNOWN`.

**Critical distinctions:** Futu callback-processing latency is *not*
provider network/ingestion RTT, so its value is not passed as a source
race measurement. A CN provider REST request's last latency may be printed
as an observed single request but never converted to unique-event P95.
A valid 15m bar, present cache, healthy heartbeat, or a source name on the
enum does not prove entitlement or production qualification.

The workflow refuses a deployed MCP repo SHA that differs from GitHub
`main`. This prevents accidentally testing stale deployed readers. It
uses SSM to run a fixed script, without restarting systemd or changing
AWS IAM, source providers, canonical writer ownership or Radar.

Only whitelisted status/symbol/timeframe, cache count, rejection gate names,
non-sensitive time measurements and safety controls appear in the workflow
result. No OHLCV, raw provider payloads, API keys, account data, host
configuration or error messages are printed.

## Next engineering gates

1. Distinct unique source-event IDs, provider timestamps and freshness
   windows for both live providers, including market-specific closure rules.
2. Cross-check two independently licensed sources and persist provenance,
   dropped updates, out-of-order, disconnects, reconnect durations.
3. Construct durable writer lease/fencing protocol: per-symbol/timeframe
   single-writer guarantee is not achieved by this shadow proposal.
4. Cloud-to-Desktop health evidence and PC-off witness before automatic
   fallback. Cache-level performance is not the full end-to-end SLO.
5. TickFlow paid qualification only after the user reports buying Expert
   and keys are provisioned **outside ChatGPT/repository/logs**, with official
   simultaneous AWS/Desktop account rights confirmed.

Invariant: `canonical_writer_created=false`, `proposals_admitted=0`,
`data_qualification=NOT_VERIFIED`, `radar_admission=BLOCKED`,
`live_trade=false` and `can_confirm_signal=false`.

## Two-sample unique-event progress witness (V0.2)

The cloud audit now reads the existing source caches twice, with a 12-second
sampling interval. It explicitly reports:

- US: health heartbeat sequence, provider callback event count,
  **accepted** event count, canonical snapshot sequence, and reported
  session state. Advancing heartbeat sequence with unchanged accepted event
  count is **not** interpreted as active market data.
- US closed market: unchanged provider event count is classified as
  `CLOSED_SESSION_NO_ADVANCEMENT_NOT_FAILURE`, not a provider outage.
- CN: observer polling sequence vs 15m last-bar label progression. A cloud
  observer heartbeat may advance repeatedly while the current/last complete
  15m bar stays unchanged. That is **not** proof of lost ticks.
- CN provider switching (Tencent/Eastmoney) and event counter reset are
  called out separately. Provider raw bars and bar time labels are not
  printed, only classified change states.

No accepted-event delta or last-bar change becomes `source_progress_qualified`;
independent exchange source event lineage, entitlement, completeness,
reconnect, cross-source finality and cloud desktop-off witness are still
required. This adds actual time-separated **AWS cache** observations, **not**
end-to-end P50/P95/P99 or continuous subscription admission.

The AWS SSM command timeout remains 120 seconds and GitHub workflow remains
manual. No new daemons, paid endpoints or canonical writes.

## US session and Canonical chain triage (V0.3)

The shadow-only probe now reuses the existing
`futu_us_market_state_to_session` classifier instead of accepting invented
generic `OPEN/PRE_MARKET` enum values. The actual Futu `MORNING` and
`AFTERNOON` map to regular session; premarket, after-hours, overnight and
closed states remain distinguishable. Unknown/new provider states stay
`unknown` rather than silently being called regular or closed.

US two-sample progress includes `market_session`, sanitized
`canonical_export_status`, `canonical_snapshot_status`,
`canonical_snapshot_age_seconds` and
`canonical_chain_classification`. The triage distinguishes
`EXPORT_NOT_CONFIRMED`, `EXPORT_PASS_SNAPSHOT_STALE_CAUSE_UNKNOWN`,
`ACCEPTED_CALLBACKS_SNAPSHOT_UNCHANGED_CAUSE_UNKNOWN`,
`BOTH_COUNTERS_ADVANCED_UNQUALIFIED` and
`CANONICAL_PROGRESSION_NOT_VERIFIED`.

**Interpretation limits:** An export heartbeat reporting PASS while a
snapshot has aged beyond its freshness window is an observed mismatch,
not proof of a broken OpenD provider. A callback delta without a Canonical
sequence delta can legitimately occur while a 1m bar is still forming.
Non-regular-session silence is not classified as a provider failure.
Missing counters and unknown session states remain unqualified. No
provider RTT, latency P50/P95/P99, source entitlement, independent
stream progress or automatic failover is inferred. This is only
read-only evidence for distinguishing service liveness from bar freshness.
All Data/Radar/Execution controls remain fail-closed.

## Read-only US Canonical ↔ Radar sequence witness (V0.4)

The same AWS two-sample shadow audit now reads the already-running **US Radar
research heartbeat** through `read_us_radar_analysis` (no worker restart or
new daemon). It records sanitized reader/poll status, worker heartbeat sequence,
Radar-reported source sequence and an **unqualified** comparison against the
Canonical snapshot sequence and SHA. Raw Runtime IDs and provider data are
not emitted; only whether runtime identity stayed stable is reported.

- `radar_worker_poll_sequence=ADVANCED` is **not** evidence of incremental
  market analysis. Repeated polling of the same Canonical sequence yields
  `WORKER_POLL_ONLY_NOT_INCREMENTAL`.
- `radar_source_sequence_progress=ADVANCED` with stable source identity and
  matching SHA yields `SOURCE_SEQUENCE_ADVANCED_UNQUALIFIED`. Equality of two
  cached sequence numbers does not establish a unique exchange event or
  event-to-Radar latency.
- Missing, stale or mismatched repository evidence is classified explicitly,
  without upgrading it to a matched/qualified source.
- A changed runtime identity scopes counters as
  `RUNTIME_CHANGED_UNQUALIFIED`. A session transition is not assumed to be
  a normal idle interval.
- `radar_increment_proven=false` remains invariant, independent of the
  worker's `radar_analysis_performed` flag. Cache polls and precomputed
  telemetry are not admitted as fresh Data→Radar latency distributions.

This is diagnostics for the already-deployed worker on the fixed AWS SSM host.
It does **not** create a Radar incremental event tracker, a measured provider
network SLO, an event lineage chain, source authority, or a live execution
path. Non-applicable/absent Radar caches remain fail-closed.
