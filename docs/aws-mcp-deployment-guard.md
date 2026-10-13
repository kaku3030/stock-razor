# Canonical read-only MCP deployment: owner/main/OIDC and SSM guards

`.github/workflows/deploy-readonly-mcp.yml` is an **explicit, manual**
production service deployment. The installer restarts only
`stock-razor-mcp.service`. It is not a diagnostics-only AWS audit, and
creating or merging a PR never dispatches this workflow.

## Fail-closed deployment envelope

The workflow now accepts a deployment only from the authenticated repository
owner and the protected `main` ref. Its checkout is the immutable
`github.sha` with persisted Git credentials disabled.

Before AWS OIDC and **again immediately before SSM**, the job compares
the checked-out commit to GitHub's latest protected main SHA. A queued or
superseded dispatch aborts; it never silently upgrades to the new main or
falls back to a mutable branch.

The reviewed installer SHA256 is calculated from that checkout, then the
remote short-lived SSM command checks the downloaded **exact commit** bytes
against the reviewed checksum before executing the installer. The remote
installer runs inside a temporary directory with restrictive permissions;
raw installer stdout/stderr stays in temporary files and is never emitted
to this public repository's GitHub Actions logs. Only an allowlisted
`systemctl is-active` success marker enters deployment acceptance.

The workflow continues to use the existing fixed AWS account, role, Tokyo
region and EC2 instance. It does **not** provision an additional role, open
ports, change broker accounts, access new secrets or grant ChatGPT arbitrary
remote shell permissions. It keeps no new schedule or comment trigger.

## Validation gates

1. Run the exact-head PR CI and focused tests. The shell tests mock GitHub
   main discovery and confirm denial for wrong actor/ref, malformed checkout,
   stale head and GitHub API failure **before OIDC**.
2. Verify installer checksum ordering, main-SHA recheck before SSM, and no
   uncensored SSM stdout/stderr in public logs.
3. Only a separate, intentional owner-initiated `workflow_dispatch` can
   perform a production service restart. CI success is **not deployment**.
4. An explicit future deploy still needs independent, post-restart cloud MCP
   source/protocol acceptance. Stock data freshness and Radar/Live trading
   admission never follow automatically from a service restart.

**Current governance:** `SOURCE_ARBITER_ADMISSION=BLOCKED`,
`RADAR_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO`,
`TRADE_EXECUTION=NO`.

## Limitations and rollback

The installer currently fetches its contents from public GitHub at a pinned
SHA and clones the repository. This change does **not** claim the deploy
path is private-repository compatible; that requires separate private-safe
source transport and acceptance. Rollback reverts the workflow and tests,
without changing any running EC2 services.
