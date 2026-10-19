# STOCK RAZOR Cloud Ops — read-only phase

This phase reuses the **existing** AWS EC2 instance and canonical read-only
MCP deployment. It is deliberately not a new AWS administration account,
SSM remote command executor, or unrestricted shell.

## ChatGPT tool

`get_cloud_ops_status` reads a fixed list of four existing service units and
their **local**, bounded JSON heartbeat files through the reviewed
`scripts.audit_cloud_runtime_readonly.component_snapshot` contract:

- US LiveFeed and US Radar
- CN Eastmoney observer and CN Radar

It projects **only** whitelisted states, heartbeat ages, sequences, source
revisions and safety-evidence enums. It does not return process environments,
logs, commands, file paths, provider payloads or credentials. It neither
invokes AWS EC2/SSM/CloudWatch APIs nor modifies or restarts units.

`ok=true` means all four service heartbeats were observed recent with
complete explicit safety flags, **not** qualified real-time bars, evidence of
PC-off independence or permission to execute any trading/Paper task.
`source_arbiter_admission=BLOCKED`, `radar_admission=BLOCKED`,
`paper_auto_ready=false`, `live_trade=false` and
`mutation_allowed=false` are immutable in the tool.

## ChatGPT legacy action snapshot: CN Fast Report compatibility

The existing ChatGPT STOCK RAZOR action manifest currently exposes
`get_cn_market_analysis` but may not yet expose the separately deployed
`get_cn_quick_scan`. Until the app actions refresh, the same read-only
MCP endpoint supports **exactly** `get_cn_market_analysis(symbols=["__QUICK_SCAN__"])`
as a backward-compatible routing request, returning the **existing**
`stock_razor_cn_quick_scan_v0_1` compact research schema.

All ordinary requests (including empty/default, real six-digit symbols,
and other invalid symbols) keep the pre-existing Radar analysis response.
No provider network call, trading admission, bar-finality claim, mutation,
or new MCP action is introduced. A returned `BLOCKED` with reason codes is
a safe diagnostic result, **not** report success. A successful server-local
quick scan is not proof of a faster ChatGPT/iOS command-to-answer latency;
measure real tool wall time and client delivery separately.

## Owner-only GitHub transport for read-only AWS diagnosis

The existing `audit-cloud-independent-runtime.yml` workflow can also be
requested from the authenticated repository owner's linked GitHub account,
without logging into AWS or keeping a personal PC online:

- Post exactly `/stock-razor aws-audit read-only` on **PR #665**.
- GitHub's `issue_comment.created` event reaches AWS OIDC only if the
  authenticated actor/comment author/repository owner, merged-PR number and
  literal command all match. A separate Python gate rechecks the signed-by-
  GitHub event payload before IAM/OIDC; checkout SHA and remote main SHA are
  checked again immediately before SSM.
- The existing fixed-instance, immutable-SHA audit reads four cached cloud
  heartbeat/service facts. It cannot restart EC2, change IAM, fetch secrets,
  modify data providers, place Paper/Live orders or change safety admissions.
- A new comment is one explicit read-only request, **not** a timer or scheduled
  monitoring task. Invalid or untrusted comments are skipped or blocked.
- Inspect the exact `Audit Read-Only Cloud Runtime` run in GitHub Actions.
  A SUCCESS result proves the bounded AWS audit executed; it does not prove
  new ChatGPT MCP tooling, trade qualification or continuous off-PC uptime.

Do not interpret a PR/CI pass alone as a tested owner-comment→AWS path. That
requires a real comment-triggered run from the expected owner and examination
of its sanitized evidence. If the remote main SHA moved, the audit must refuse
to run; never bypass this with an older revision.

## AWS heartbeat timestamp race (diagnostic correction)

The 2026-10-13 real GitHub→AWS SSM two-sample audit [run
#38359901810](https://github.com/kaku3030/stock-razor/actions/runs/38359901810)
reported US Radar `CLOCK_REVERSAL`; independent real
[run #38361094660](https://github.com/kaku3030/stock-razor/actions/runs/38361094660)
repeated that classification. This **did not prove AWS clock skew**.

The original audit captured one wall clock **before reading four
independently updated JSON caches**. US Radar publishes roughly four
heartbeats per second, so the heartbeat file could be atomically replaced
after the audit sampled time but before it loaded JSON, spuriously making
the heartbeat "from the future."

The read-only AWS audit now captures **before and after clock readings for
each individual cached file**; the later clock measures the loaded heartbeat
age. Cloud Ops local MCP health does the same for live execution. Synthetic
regressions cover concurrent publication, genuine future timestamps, real
backward clock movement, invalid clocks and the unchanged trading blocks.
If the post-read timestamp is still in the future or the clock runs
backwards, the audit remains fail-closed.

**Verification:** code/CI tests alone do not prove the original cloud
incident resolved. Repeat the authenticated owner-only read-only SSM
audit using the *merged main revision* and inspect actual US Radar
status/sequence progression. Never promote operational heartbeat health
to qualified market data, Radar admission, or Paper/Live trading.

## Deployed MCP source inventory (AWS read-only)

The owner-only AWS SSM runtime audit also checks the fixed EC2 MCP
service and its **installed** Git checkout. The redacted
`mcp_deployment_evidence` includes only:

- whether the fixed `stock-razor-mcp.service` unit is active;
- a 40-character validated deployed Git SHA (or null);
- whether the installed Python source structurally declares the
  `@mcp.tool()`-decorated `get_cloud_ops_status`;
- `authenticated_protocol_verified=false` **always**.

`SOURCE_PRESENT_PROTOCOL_NOT_VERIFIED` is *not* proof that ChatGPT can
invoke the cloud tool, nor that the running process imported it, nor
permission to restart/alter EC2. A direct authenticated protocol read and
fresh remote health evidence are separate acceptance steps.

This inventory adds no new workflow event, AWS permission, host command
execution beyond fixed read-only Git revision checks, service writes,
data-provider I/O, timer or external notifications. The existing
`audit_status` remains the four-service heartbeat verdict, independent
of the MCP installation inventory. Existing trading/signal gates remain
blocked.

## Existing ChatGPT action compatibility (read-only)

The cloud server already declares `get_cloud_ops_status` but older ChatGPT
connector registrations can still expose only the legacy eight actions.
To allow read-only diagnostics **without** a new client-side tool name, the
already registered `get_market_analysis` action recognizes exactly this
otherwise-nonmarket argument:

`symbols=["__CLOUD_OPS_STATUS__"]`

That literal **single-element** list delegates to the same vetted local
`read_cloud_ops_status()` used by the native `get_cloud_ops_status`.
It does not issue provider/AWS requests, deploy code, start/stop services or
modify any trading gate. All other requests, including real US tickers,
omitted symbols, mixed lists, other spellings, and malformed input retain the
original US Radar implementation and schema.

**Acceptance boundary:** GitHub CI and installer smoke prove code behavior,
not that ChatGPT can call the new route. The immutable SHA must first be
deployed through the existing separately authorized MCP deployment workflow,
then the **current ChatGPT session's registered** `get_market_analysis`
action must be called with the literal singleton sentinel; inspect the
returned `schema=stock_razor_cloud_ops_readonly_v0_1`, closed safety
gates, heartbeat ages and read-only metadata. Do not infer deployment from
successful PR merge or source presence on an older EC2 revision.

This compatibility path is **diagnostic only**, not an unrestricted AWS
management API. It does not qualify market-data freshness, a live trading
signal, or continuous off-PC uptime. No new timed task or credential is
introduced.

## Integration / acceptance gate

1. Verify the exact-commit PR tests and installer smoke in CI.
2. A separately authorized operator may, **after review**, deploy the approved
   main SHA through the existing protected manual read-only MCP workflow.
   This PR itself does not dispatch AWS Actions or restart any cloud service.
3. Confirm that the remote authenticated MCP actually lists the new tool, and
   retrieve a sanitized Cloud Ops result from the EC2 host. A tool on GitHub
   is not the same as an available tool in an existing ChatGPT session.
4. Direct AWS administration (e.g. EC2/SSM actions, CloudWatch queries) remains
   **NOT CONNECTED**. That requires an independently authenticated management
   transport, least-privilege AWS authorization, an exact operation allowlist,
   audit events, rate limits, and independent fail-closed tests. Do not reuse
   broad GitHub OIDC or instance-role permissions for unrestricted chat calls.

## Rollback

Revert the isolated MCP tool, read-only reader, test, installer smoke and
changelog patch. No IAM, database, broker or source migration is involved.

## Guarded CN Radar deployment

`Deploy Read-Only CN Radar Worker` is manual, owner-only and bound to the
current full main SHA. Set `approve_restart=true` and provide
`expected_main_sha`; the workflow checks main before AWS credentials and again
before SSM. Both immutable installer/verifier downloads must match their source
SHA256 before restart. Installation and full verifier output stay private on EC2;
public Actions logs contain only fixed deployment/safety markers. Missing proof,
remote failure or a moved main blocks deployment success. Roll back by dispatching
a separately reviewed revert on protected main.

The workflow's `source_provider` choice defaults to `eastmoney` (the existing
Eastmoney/Tencent observer). Explicit `tickflow` selects the existing private
TickFlow cache for **historical research only**, using the same CN Radar service,
status file, analyzer and `get_cn_market_analysis` readback. The installer binds
each choice to its fixed cache path and source unit; arbitrary `SOURCE_PATH`
overrides are no longer used. No SDK, network access, extra polling service or
provider request is introduced. `RADAR_ADMISSION=BLOCKED` and `LIVE_TRADE=NO`.

TickFlow evaluates only the four existing baseline symbols and cached D1/60m/15m.
The strict cache reader validates all rows from one bounded atomic snapshot.
Every poll rechecks source age, including unchanged evaluations; atomic file
replacement invalidates the compute cache even when sequence metadata repeats.
Same-day D1 is quarantined. Intraday bars remain partial, currentness UNPROVEN,
finality/volume units/adjustment NOT_VERIFIED. Vendor operational-close rules
are not promoted to immutable finality by this bridge. Source runtime UUID is
NOT_VERIFIED because the collector does not publish one. Current D1 cache depth
is at most 40 bars: this is not the full long-history/L3 strategy prerequisite.
The first actual cloud bridge readback contained D1=40, 60m=4 and 15m=16
rows per baseline symbol. Requested SDK counts are not evidence of returned
depth. Insufficient-history indicator states retain the caller's partial-bar
flag, bar count, latest label and explicit warnings; TickFlow also reports
`tickflow_indicator_history_insufficient`. Operational bridge verification
does not turn these short histories into qualified multi-timeframe signals.

The TickFlow deployment verifier independently rereads the source SHA, sequence
and observation time, verifies all four research states and provisional flags,
and requires the existing network sandbox and closed gates. CI or a fixture
does not prove deployed integration: dispatch the exact main SHA with the chosen
provider, then read actual MCP provenance. Roll back the provider choice by
dispatching protected main with `source_provider=eastmoney`; no source collector,
subscription, durable market-data store or trading state is modified.

For US Radar with research events enabled, operational deployment verification
also accepts the precise `BAR_EVENT_SOURCE_NOT_QUALIFIED` block only when the
source remains unqualified, the ingress is explicitly blocked, and it created
and duplicated zero events. Queue types, source SHA and all safety checks still
apply. This verifies fail-closed service behavior, not market-data qualification.

The verifier also requires the existing 90-second service watchdog. `systemctl
show ... -p WatchdogUSec --value` formats this duration as `1min 30s` (or
`90s`); the property suffix does not make its display a raw microsecond integer.
Zero, other durations and a unitless `90000000` fail verification. The full shell
acceptance path is tested in addition to the embedded heartbeat checks. See
[systemd's property formatter](https://github.com/systemd/systemd/blob/v255/src/shared/bus-print-properties.c).


## US OpenD 15-minute cloud research digest (2026-10-19)

The dedicated `.github/workflows/us-opend-15m-research-notify.yml` runs a best-effort
GitHub Actions cron every 15 minutes in the US-market UTC window and checks the
pinned XNYS exchange calendar before any AWS OIDC/SSM action. It reads the existing
EC2 OpenD LiveFeed heartbeat and canonical bar cache plus the US Radar research
heartbeat. It never calls the provider or a paid model, changes subscriptions,
restarts services or places orders. The runner sends its bounded Chinese research
summary only to the existing `DISCORD_RADAR_WEBHOOK_URL` GitHub Actions secret.

The report distinguishes D1 historical research (Radar state) from 1H/15m cache
readbacks. Source age uses last actual K-line timestamp, not the refreshed
heartbeat. Any missing, old, non-OpenD, provisional, unhealthy, version-mismatched
or non-final bars produce `BLOCKED` and no confirmed trade signal. This is
read-only research monitoring, not qualified L3 Radar admission.

Manual dispatch defaults to `dry_run=true`, so it validates the path without
Discord notification. Scheduled runs notify during exchange sessions only;
concurrent runs are serialized and manual reruns do not double-send. GitHub cron
may start late or skip, so this is **not** a guaranteed clock-exact 15-minute
SLA. Receipt must be independently verified from Actions and Discord, and a
matching source-deployed SHA must be proven separately from a passing workflow.
If the webhook secret is missing/invalid, the notification step fails closed.
Rollback: revert/disable the dedicated workflow; existing LiveFeed/Radar workers
are unchanged. The separate ChatGPT hourly automation is unaffected.
