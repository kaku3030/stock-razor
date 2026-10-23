# OpenD runtime publication and missing-source diagnosis

Scope: Hybrid V1.0 AWS quote collection only. Windows owns Radar, strategy,
backtests, risk and trading. This change does not start any strategy service,
add a provider, change subscriptions, or change admission gates.

## Confirmed defects and evidence limits

- The heartbeat, canonical snapshot and daily-history publishers used a shared
  `<destination>.tmp`. Two writers synchronized immediately after file fsync
  reproduce `FileNotFoundError` at replace in all three production publishers.
  The regression initially produced 9 failures / 3 passes, including staging
  cleanup failures and heartbeat acceptance of nonfinite JSON.
- `CanonicalSnapshotRadarWorker.poll_file` returns unknown source safety when
  its input is missing or malformed. The US reader interpreted that failure as
  `EVALUATION_SAFETY_CONTRACT_VIOLATION`. Real worker-to-reader tests reproduced
  both cases. The reader now preserves `SOURCE_UNAVAILABLE`, the source reason,
  and unknown source safety. Contradictory or unsafe results remain invalid.
- These are code defects. **Neither proves why the October 23 production
  heartbeat and snapshot disappeared.** Service exit, reboot, sandbox access,
  startup blocking, deployment and mount visibility require host evidence.

The direct MCP health and snapshot reads during this investigation both returned
`FileNotFoundError` for their respective `/run/stock-razor-us-livefeed` files.
The last independently found LiveFeed deployment record was
[run 39112056147](https://github.com/kaku3030/stock-razor/actions/runs/39112056147),
October 18 at source `896f05d4f01763a75413e4cf40d40288e4435c0e`.
The October 23 MCP deploy
[39955687079](https://github.com/kaku3030/stock-razor/actions/runs/39955687079)
does not establish the current LiveFeed process revision.

## Publication contract

`runtime_publication.write_runtime_json` is shared by heartbeat, canonical and
daily files. It validates JSON before writing, allocates a unique staging file
in the destination directory, flushes/fsyncs, replaces atomically, and fsyncs the
parent directory on POSIX. Failed staging files are cleaned; exceptions propagate.
Existing access mode is preserved; new quote-only files retain 0644 for the
independent reader service. The heartbeat no longer serializes NaN/Infinity.

Each file is atomic individually. Concurrent publication is last-replace-wins;
it does not establish sequence ordering or a cross-file transaction. Existing
runtime/SHA/sequence/freshness checks remain necessary. A process killed before
replacement may leave its own unique staging file; later writers ignore it.
No cleanup job deletes files belonging to other live writers.

`/run` remains ephemeral. systemd `RuntimeDirectory` removal on service stop or
host reboot can remove evidence. This patch does not turn it into durable history,
guarantee reconnect/backfill, or prove three-session continuity.

## Host investigation required before production attribution

Use the existing allowlisted `AWS SSM Ops` diagnostics. First capture read-only
evidence, without restarting or deleting anything:

1. Compare LiveFeed and OpenD units' active/sub states, exit status, restart
   count, execution and start timestamps, actual executable, working directory,
   sandbox mounts and runtime-directory ownership/mode.
2. Read the LiveFeed unit's configured SHA and installed repository SHA;
   compare embedded `run.py` with that exact installer's generated source.
   MCP deployment SHA is a separate fact.
3. Inspect existence, inode, mode and timestamp for heartbeat, canonical and
   daily files from both producer and MCP reader mount namespaces. Inspect
   configured path variables: producer uses `STOCK_RAZOR_CANONICAL_SNAPSHOT_PATH`,
   reader uses `STOCK_RAZOR_US_CANONICAL_SNAPSHOT_PATH`; defaults match, but custom
   overrides need explicit comparison.
4. Inspect private service journal around the first failure and previous boot.
   Classify startup/OpenD connect, SDK logging/sandbox, filesystem/permission,
   serialization and provider failures. Retain raw logs privately; publish only
   sanitized error categories and immutable evidence references.
5. Verify provider permissions, fresh callbacks and bar timestamps separately
   from process/port health. Keep unknown closure and stale data blocked.

The initial direct tools had no AWS execution credential or workflow dispatch
API, and the existing Windows remote device was offline. The permitted browser
fallback subsequently reached the existing signed-in GitHub workflow UI and
restored read-only SSM diagnostics. No IAM change or new credential was needed.

[SSM status run 39978609341](https://github.com/kaku3030/stock-razor/actions/runs/39978609341)
returned `BLOCKED / RUNTIME_OR_CACHE_NOT_PROVEN`. The independent existing
[cloud runtime audit 39978736070](https://github.com/kaku3030/stock-razor/actions/runs/39978736070)
confirmed `unit_active=true` and `HEARTBEAT_UNAVAILABLE` for LiveFeed. The legacy
US Radar worker remained active with a blocked evaluation; the audit does not
start or authorize that worker. MCP source was still `eebb8ec4`, independently
of the newly merged application revision. The exact current LiveFeed process
SHA and the cause of missing publication remain **NOT_VERIFIED**.
No restart, deployment, automatic recovery schedule or new paid resource was
created by these diagnostics. Existing restart window protection remains in force.

## Bounded host diagnostics

The existing `us_livefeed_status` action now ships its exact checked-out stdlib
diagnostic helper through the existing SSM payload. `runtime_diagnostics` exposes
only allowlisted systemd states, last exit/restart counts, process elapsed time,
installed source hashes, the three fixed files' type/mode, and bounded journal
exception-family counts. A regular file type is not a readability or valid-JSON
claim. Journal counts are sample observations, not proof of a root cause.

Both the producer and public-output projector enforce the same strict field and
type allowlist. Raw journal text, command arguments, environment, arbitrary paths
and private identifiers never enter public output. Each subprocess is byte and
deadline bounded; an EOF-producing child that stays alive is killed. This is a
read-only diagnostic, with no OpenD provider request, restart, recovery or gate
change. The existing protected-main postmerge workflow dispatches one observation;
its actual output must be checked separately from CI.

## Completion and rollback

Run focused publication, canonical reader/export, daily-history, installer,
worker and US reader tests; require exact-head CI before integration. Deploy
through the existing guarded LiveFeed workflow only after host diagnosis.
Verify cloud failure/recovery, all requested timeframes including 4H, actual
subscription changes/reconnect/backfill and Windows parity independently.
Three full regular sessions require preserved runtime evidence for each entire
session. Historical warm start and short verifier PASS cannot count as sessions.

Rollback is a normal revert of this patch followed, if deployed, by the existing
guarded deployment of the previous exact revision. No data migration is needed.
Retain `RADAR_ADMISSION=BLOCKED`, `SOURCE_ARBITER_ADMISSION=BLOCKED`,
`PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO` throughout this diagnosis.
