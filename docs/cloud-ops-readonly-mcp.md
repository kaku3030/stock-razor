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
