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
