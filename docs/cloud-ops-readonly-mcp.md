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
