# ECT Feedback Hub: EC2-only read-only storage qualification

This acceptance lane verifies **an already-existing** SQLite Feedback Hub database on
the authorized EC2 target. It does **not** initialize, repair, migrate, mount or
write to that database. No service is started, restarted or deployed.

## Required GitHub repository variables (non-secret control values)

Configure these repository **Variables** only after the AWS target and shared
storage design are independently approved:

- `FEEDBACK_HUB_PATH`: absolute existing path **on the EC2 target** to the
  SQLite file. Do not use a GitHub runner-local path, `/run`, `/tmp`,
  `/dev/shm`, a symlink, a missing path or a non-durable mount.
- `STOCK_RAZOR_ECT_EC2_INSTANCE_ID`: existing authorized EC2 SSM target ID.
- `STOCK_RAZOR_GITHUB_OPS_ROLE_ARN`: already approved existing OIDC Ops
  role with read-only investigation permissions as needed; this PR grants no IAM
  permissions.

A GitHub Actions variable **never mounts** a remote SQLite filesystem. The
manual workflow transmits only an explicitly bounded path as part of a
sanitized AWS SSM request and performs the read on EC2 instead.

## Manual workflow

`.github/workflows/audit-feedback-hub-ec2-readonly.yml` is
`workflow_dispatch` only, `confirm=false` by default, repository owner
only, exact `main` checkout+SHA gated, no schedule or automatic reruns.
Requires existing GitHub OIDC/SSM rights. The remote script is sourced from
the exact protected main revision and its SHA-256 bytes are verified
before execution. It stages its own temporary probe file and cleans it up.

Output is intentionally limited to: fixed status codes, schema-version state,
a conservative mount type classification, open P0/P1 counts, total audit count,
and a **truncated SHA-256 digest** of the last 16 audit event IDs. No paths,
record IDs, titles, source references, raw OHLC, model data, auth values or
SQL exception text are displayed.

`READBACK_ONLY` means a non-volatile-type filesystem, SQLite schema v1,
quick-check and bounded count/tail reads were observed **at this instant**.
If the file is absent, corrupt, in an ephemeral path or on an unknown mount,
the workflow must fail closed; no database is created.

## What this does not prove

- No independent-run storage durability or EC2 restart survival.
- No provider/US/CN producer messages actually submitted.
- No atomic claim/lease/retry/writeback from a second worker.
- No downstream Radar data quality, market-data finality, Paper L2 or trading.
- No assurance that older database rows lack sensitive text; assess separately.

A subsequent independent read with a changed audit count/digest can be part of
a **future** controlled persistence test, but this workflow never writes a
sentinel and cannot by itself qualify persistence. Repeated identical digests
also do not prove recovery from host loss or reboot.

Keep `SOURCE_ARBITER_ADMISSION=BLOCKED`, `RADAR_ADMISSION=BLOCKED`,
`PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO` and `TRADE_EXECUTION=NO`.
