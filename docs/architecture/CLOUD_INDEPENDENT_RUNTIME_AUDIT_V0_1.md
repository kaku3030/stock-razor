# US/CN AWS Independent Runtime Audit V0.1

Status: **read-only operational evidence probe**; not a trading or data-admission
qualification. Based on the already-deployed GitHub OIDC → AWS Systems Manager
control plane.

## Motivation

A local Eastmoney/GM 15m/60m test and historical AWS deployment logs do **not**
prove that an AWS instance is currently collecting, or that the system will
remain functional while the user's computer is off.

The workflow `Audit Read-Only Cloud Runtime` is manually dispatched on `main`.
It uses temporary GitHub OIDC credentials and an SSM read-only command; no
personal desktop application, Futu client, or locally running GM is used to
read the EC2 runtime files. Its output is a whitelist-only JSON summary.

## Read-only evidence inspected

- US OpenD livefeed heartbeat and its systemd unit;
- US precomputed Radar worker heartbeat and its systemd unit;
- CN Eastmoney/Tencent cloud observer heartbeat and its systemd unit;
- CN precomputed Radar worker heartbeat and its systemd unit.

For each: `unit_active`, `heartbeat_age_seconds`, `sequence`,
`operational_state`, `safety_evidence`, validated commit SHA and bounded
Radar compute/finish measurements (where directly present). A two-sample,
15-second window reports whether a component's heartbeat sequence advanced.

It deliberately does **not** print raw market payloads, error messages,
configuration, environment, credentials, API responses or customer data.
Malformed/missing/stale evidence and unexpected governance fields are recorded
without any attempt to restart or repair services.

## Independent controls

1. `HEARTBEAT_CURRENT` proves only a bounded operating heartbeat, **not**
   current market bars, quote entitlement, qualified data, lower latency,
   signal permission or a specific provider.
2. OpenD callback processing timing is not network RTT, and cloud service
   uptime is not evidence of provider market-feed coverage.
3. Some older US livefeed heartbeats omit `research_only` and
   `can_confirm_signal`; they yield `safety_evidence=INCOMPLETE` rather
   than guessed PASS. Any explicit admission/trading promotion is INVALID.
4. Even all four services active with advancing sequences leaves
   `off_pc_independent_acquisition=NOT_VERIFIED`: proving computer-off
   independence requires a controlled host-off witness and actual market bar
   progression while US/CN sessions are open.
5. No changes to AWS IAM, paid resources, app services, running process
   topology, Provider fallback, Radar admission or trading modes are made.
6. The workflow result `success` means **audit executed**, not cloud
   production or Data Admission PASS. Interpret `audit_status`,
   `all_components_current`, individual status, and missing evidence.

## Next acceptance gates

- Run the pinned SSM audit and inspect the sanitised per-service evidence.
- Fix any missing/stale/safety-incomplete fields in a separate reviewed CI slice.
- During respective market sessions sample changing source sequences **and
  new market bars**; verify source lineage, bar finality, timestamp, provider
  entitlement, completeness and quote freshness.
- Deliberately power off the user's desktop and capture its independent status
  simultaneously with continuous AWS feed/data/Radar evidence.
- Run sustained P50/P95/P99 per unique provider/source-sequence, instrument
  MCP and end-to-end request latency; do not treat repeated cache reads as
  independent samples.
- Only a separate qualification decision may change Data or Radar Admission.

`RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`,
`can_confirm_signal=false`.
