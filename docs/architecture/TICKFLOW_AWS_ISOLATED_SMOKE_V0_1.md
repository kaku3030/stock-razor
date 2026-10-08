# TickFlow AWS Tokyo isolated capability smoke V0.1

**Scope:** Cloud support for *isolated research probe*, not a new production
market-data source, not canonical writer, not Source Arbiter admission.

This enables the user-requested two-location TickFlow evaluation without
requiring their Windows desktop to stay powered on. A manually dispatched
GitHub Actions workflow runs an isolated SDK environment on the existing Tokyo
EC2 instance (ap-northeast-1) via temporary GitHub OIDC credentials and AWS
Systems Manager. The workflow can be initiated from mobile or computer.

## Implementation

- Workflow: `.github/workflows/probe-tickflow-aws-isolated.yml`.
- Remote bootstrap: `ops/aws/run_tickflow_cloud_isolated_smoke.sh`.
- Official SDK: `tickflow==0.1.25`, with the existing pinned requirements.
- Dedicated AWS venv: `/opt/stock-razor-tickflow-isolated/venv`.
- Source SHA is anchored to the workflow checkout of protected `main`.
  Bootstrap, probe source and requirements each have a SHA256 integrity check
  against the runner checkout before execution.
- Supported modes **without official purchase**: `metadata` (no network
  data request) or `free` (at most one historical 1d K-line request).
- Paid `premium` / WebSocket deliberately blocked in the AWS workflow until
  the user reports official purchase, secure AWS credential provisioning,
  provider IP/overseas/concurrency rights and rate-limit qualification.
- Cannot access `TICKFLOW_API_KEY`; SSM script explicitly unsets potential
  key env and never reads SSM SecureString or Secrets Manager.
- No deployed systemd service, order, subscription, canonical update,
  provider failover/routing change, paid plan purchase or live trade.

## Stage acceptance

1. CI: static YAML integrity, narrowed SSM scope and isolation tests pass.
2. AWS: run `TickFlow AWS Isolated Smoke` → metadata, report
   `TICKFLOW_CLOUD_SDK_IMPORT=PASS` and isolated provenance.
3. AWS: optionally run `free` and record one historical daily REST query
   operation status. This is **not** a latency distribution and cannot prove
   minute/real-time entitlement.
4. Credential/country rights checked separately before premium AWS probe.
5. During A-share session, collect original feed timestamps, unique events,
   continuity and P50/P95/P99 at AWS Tokyo and desktop, plus cross-check
   Eastmoney/Tencent/TDX; only then prepare a qualified source candidate.

A GitHub Actions **success** establishes that isolated setup and its
sanitized probe ran. It does not prove the user's PC was powered off,
continuous cloud WebSocket or real-time A-share data quality. This slice
always prints `cloud_independence=NOT_VERIFIED`,
`real_market_slo=NOT_VERIFIED`,
`data_qualification=NOT_VERIFIED`,
`source_arbiter_admission=BLOCKED`,
`radar_admission=BLOCKED`, `live_trade=false` and
`can_confirm_signal=false`.

## After purchase

Use an authorized secret store with minimum access, confirm TickFlow allows
AWS Tokyo and concurrent desktop+cloud use, and only then add an isolated
premium probe in a separate PR. Secret values must never be passed as workflow
inputs, command-line arguments, repo files, CI output, logs or ChatGPT text.
