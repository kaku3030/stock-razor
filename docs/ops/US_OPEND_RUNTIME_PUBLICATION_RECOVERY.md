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

## Evidence-backed startup failure mechanism

The protected-main postmerge [SSM run39980775405](https://github.com/kaku3030/stock-razor/actions/runs/39980775405)
returned `ACTIVE/RUNNING`, elapsed33,811seconds, zero restarts, and all three
files `MISSING`. Its bounded recent journal sample counted117 connection-failure
lines and zero recognized filesystem/import/serialization failures. Installed
source was `896f05d4f01763a75413e4cf40d40288e4435c0e`; the observed runner hash
`39314446cebfdd82bf2fcf3213a9889448fe683a220bcc18d01471d3c4e3650e` exactly matches
that installer's generated runner bytes. This rules out a mismatched generated
runner for this observation; it does not prove the upstream gateway cause.

The exact pinned `futu-api==10.11.7108` distribution was independently inspected.
Its `futu/common/open_context_base.py` SHA256 is
`06740169d0d46fc5030526fac17f2d6d699e6a64e02c312ad5d7ea04e39b452e`. The default
synchronous constructor retries connection without a finite attempt bound.
The old runner performs connection and history warmup before its first heartbeat
and before starting its callback deadline; `Type=simple` leaves this whole phase
without a systemd startup deadline. A stalled SDK-I/O phase can therefore remain
active for hours without publishing or triggering the existing callback guard.
A live Python stack was not captured: the precise blocking call (constructor vs
later pre-publication warmup) remains unproven.

The repair publishes an explicitly blocked startup heartbeat before creating
the quote context, and reuses the existing stdlib systemd notification helper.
`Type=notify` bounds startup to900seconds, stop to15seconds, and runtime publication
stalls to a300second watchdog, with30second restart pacing and an existing-unit
start-rate limit. Readiness and watchdog are sent only after successful full
heartbeat publication; they do not promote provider currentness, bar closure or
Radar/trading admission. Imports, connection and warmup share the startup bound. The15minute startup
and5minute publication budgets account for the existing multi-symbol history
warmup and up to14 sequential daily-history RPCs; a short20/60second limit
would restart valid slow batches. These are safety ceilings, not latency targets.
A startup heartbeat never supplies synthetic quotes, subscriptions or closure.
The existing guarded deployment's SSM wait and job ceiling now cover the service
startup plus stop/import/verification budget; otherwise a valid slow startup could
outlive its deployment observer. Exact-main, source-hash and session veto checks
remain in force.

The existing status action also observes the fixed local listener and OpenD
process presence through bounded `ss`/`ps` reads, without opening a provider
connection. Absence and query failure remain distinct; presence is not quote
health. The checked-out stdlib helper is gzip/base64 embedded to retain the
16,000-byte SSM bound. Original command output never enters the public projection.

No production recovery is claimed until the guarded deployment and real host
restart/network recovery tests pass. The deployment's US session restart veto
remains unchanged. Three full sessions and Windows parity are still required.

## Quote-only import boundary after the first guarded deployment

[Deployment40050724139](https://github.com/kaku3030/stock-razor/actions/runs/40050724139)
failed within seconds. Independent [readback40050823035](https://github.com/kaku3030/stock-razor/actions/runs/40050823035)
shows repo `7e2be356` checked out, while the generated runner hash and original
process were unchanged and all three files remained missing. Failure occurred
after checkout and before replacing run.py; this is not a completed restart.

The newly imported notification submodule was individually stdlib-only, but
Python first executes its `stock_radar_v2` package initializer, which eagerly
imports yaml and other application dependencies. A minimal Python subprocess
reproduces that import failure. Move the primitive to `src.utils.systemd_notify`, retain
the existing Radar import as a compatibility re-export, and import the neutral
path in the quote-only installer/runner. Do not install the whole application
stack into the OpenD client to hide this dependency leak.

The existing read-only status diagnostic now runs the legacy import once in a
separate three-second bounded child. It never constructs a provider context or
sends systemd notifications; exception text is suppressed. Only PASS,
MISSING_YAML, MISSING_DEPENDENCY, IMPORT_ERROR or query-failure classifications
cross the public boundary. Actual host classification and a new guarded deploy
are required before claiming this production failure recovered.

## Completion and rollback

Run focused publication, canonical reader/export, daily-history, installer,
worker and US reader tests; require exact-head CI before integration. Deploy
through the existing guarded LiveFeed workflow only after host diagnosis.
Verify cloud failure/recovery, all requested timeframes including 4H, actual
subscription changes/reconnect/backfill and Windows parity independently.
Three full regular sessions require preserved runtime evidence for each entire
session. Historical warm start and short verifier PASS cannot count as sessions.

Rollback is a normal revert of this patch followed, if deployed, by the existing
guarded deployment of the new current-main revert commit after protected-main CI.
The exact-main guard does not permit deploying an old historical SHA directly.
No data migration is needed.
Retain `RADAR_ADMISSION=BLOCKED`, `SOURCE_ARBITER_ADMISSION=BLOCKED`,
`PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO` throughout this diagnosis.

## Diagnosing continued connection failure without another restart

Guarded deployment40066832209 at b972b282 reached a real blocked startup
heartbeat but failed roughly15minutes later, consistent with the900-second
startup bound; host journal evidence must confirm the exact exit classification. Later MCP reads
showed a different runtime instance with sequence0, no callbacks and no snapshot.
This proves startup publication and repeated process initialization, not working
quotes or the exact upstream error.

The existing read-only status action classifies the pinned SDK's Connect fail
messages into refused, timeout, reset, permission, unreachable and file-descriptor
limit counts, separately from InitConnect handshake failures and systemd startup
timeouts. Counts describe at most200 recent journal lines, never the full outage
history. It also binds the existing11111 listener to OPEND/PYTHON/SSH/OTHER or
UNKNOWN using ss owner metadata; a separate OpenD process elsewhere does not
prove that this endpoint belongs to it. No raw messages, PID, argv or new
provider connections are exposed. Unknown/missing owner metadata stays unknown.

Readback40073413088 narrowed the failure: listener owner OPEND,121 InitConnect
failures, no matched TCP errno family, six service restarts and two startup
timeout lines in the bounded sample. This locates a handshake-stage failure,
not its exact cause. The diagnostic now separates fixed handshake reason
families and runs InitConnect.pack_req in an isolated child with no context or
socket. It uses the current SDK's default wire format and does not mutate
configuration, enable/disable encryption, or load credentials. A serialization
PASS does not prove a server reply, login, entitlement or usable quotes.

The endpoint owner's current startup XML is inspected privately using the
bounded /proc cmdline -cfg_file override or the vendor-default file beside the
binary. Only API-port agreement, telnet conflict and RSA-configured booleans
are projected. Command-line api_port overrides take precedence. No password,
argv, filename, account, private-key path or key contents are published. This is
a current on-disk startup candidate, not proof of the already-loaded config.
Vendor contract: https://openapi.futunn.com/futu-api-doc/en/opend/opend-cmd.html

Readback40074307261 showed API port MATCH, RSA NOT_CONFIGURED and no telnet
conflict, with offline packing OTHER_ERROR. A local isolated install of the
pinned futu-api10.11.7108 with protobuf7.36.2 successfully serialized95 bytes;
this is not a cloud reproduction. The diagnostic therefore reports finite
exception classes/OS errno and strict numeric SDK/Python/protobuf versions.
No raw exception text or packet is projected. Actual cloud dependency versions
must be known before changing or pinning any shared environment.
