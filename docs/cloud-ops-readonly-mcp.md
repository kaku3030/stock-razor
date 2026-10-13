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


## Owner-issued GitHub cloud audit (PC-independent, read-only)

After the guarded audit workflow is merged to **main**, the existing
`Audit Read-Only Cloud Runtime` GitHub Actions workflow also accepts one
authenticated owner comment on repository PR #71:

```text
/stock-razor cloud-audit
```

This is a **fixed read-only** AWS SSM command channel via the already
existing GitHub Actions OIDC role, not an EC2 admin shell or a newly
installed ChatGPT AWS connector. ChatGPT can post the exact comment using
the connected GitHub app; the GitHub workflow uses the reviewed audit
script on the existing fixed AWS target, without the user's PC.

Both the job-level condition and a pre-OIDC Python gate require
`issue_comment.created`, repository owner identity/OWNER association,
the fixed PR number, and an exact command match. A pinned default-branch
checkout and two separate latest-main SHA gates reject stale GitHub runs.
The command text is **never** passed to a shell, and no arbitrary SSM
command can be selected through comments.

For evidence, inspect the resulting `Audit Read-Only Cloud Runtime`
GitHub Actions run and require successful AWS SSM completion plus its
allowlisted, redacted audit schema. A comment, workflow success or
non-stale heartbeat **alone** does not qualify TickFlow realtime bars,
off-PC independence, Paper or live-trade admission. If the App's comment
does not appear to GitHub as repository OWNER, this path fails closed.

**Out of scope:** service restart, deployment, cost-changing changes,
EC2/CloudWatch administrative API, IAM modification and order execution.
Those require a separate authenticated and reviewed management control
plane; this event bridge must not be extended to unrestricted commands.

To disable, remove the `issue_comment` trigger and its dedicated
pre-OIDC gate while retaining the existing `workflow_dispatch` audit.
