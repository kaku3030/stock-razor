# EC2 Paper offline no-order acceptance — isolated probe v0.1

Status: **source workflow prepared; not an execution record**. No AWS host
probing, service restart, SecretString, broker order, market-data subscription
or account read is authorized by this document alone.

## Exact target and provenance

- Manual workflow: `.github/workflows/probe-paper-ec2-isolated-noorder.yml`.
- Existing protected `main` workflow checkout is hash verified; script
  `scripts/probe_paper_ec2_offline_noorder.py` transferred over existing SSM
  using gzip/base64 and SHA256, with a fixed SSM instance target.
- The runtime code used by the probe is the existing
  `/opt/stock-razor-us-radar/repo`; operator explicitly pins the installed
  runtime SHA, initially `c777739bc277022f258faf2599222215e9640231`.
  A newer `main` does **not** silently become the tested AWS runtime.
- EC2 existing Python: `/opt/stock-razor-us-radar/venv/bin/python`.
  No pip install, git checkout, production store, daemon or service restart.

## Actions within the sandbox

Only `create_paper_adapter()` is available to the script. Standard network
socket connections are rejected before importing the Paper runtime. Under
a bounded <95s process, a private temporary SQLite pair is created, then:

1. Start owner, reconcile against the **internal deterministic Paper adapter**,
   record one synthetic accepted action.
2. Stop and reopen the same store with a new internal adapter; reject replay
   of the previous semantic intent **before** any adapter mutation.
3. Accept one new separate synthetic action; verify monotonically increasing
   internal `paper-order-1`/`paper-order-2` IDs.
4. Reopen again and validate both journal identities and zero new synthetic
   adapter calls. Remove temporary files when the script exits.

The script does **not** read live broker accounts, real/fake SIM inventory,
actual portfolio amounts or quote symbols. It emits only fixed evidence
status words; the GitHub workflow reads raw SSM JSON **privately** and prints
a strict allowlisted summary. No SSM stdout/stderr or raw credentials enter
PUBLIC GitHub logs.

## Acceptance and limits

A successful actual AWS execution can prove only isolated EC2 filesystem,
Python, deterministic Paper runtime and restart/idempotence for a named
installed **older** source SHA. It does **not** prove that a cloud Paper
scheduler exists, that US OpenD TickFlow data are currently qualified, that
an external SIM fill source is available, that telephone notifications are
delivered, or that native broker simulation is safe.

Manual Action dispatch must explicitly check
`approve_ephemeral_noorder_probe=true` and supply the known deployed
`expected_runtime_sha`; workflow only runs from `main`.
The US RTH session is **irrelevant** to these synthetic no-provider checks.

At all times:
`RADAR_ADMISSION=BLOCKED`,
`SOURCE_ARBITER_ADMISSION=BLOCKED`,
`PAPER_AUTO_READY=NO`,
`LIVE_TRADE=NO`,
`TRADE_EXECUTION=NO`.

This is a **P4 cloud-hosted isolated soak candidate**, not P5-qualified
market data, external Paper account admission, P6 cloud agent operation,
or an order unlock.
