# Connectivity C remote access and autonomy preparation

**Checkpoint:** 2026-10-20 JST  
**Owner:** Connectivity C  
**Base:** `main` at `7e1ca0edc7be2c099bf3638ead49f994a2cefde1`  
**Status:** preparation only; no runner registration, tunnel deployment, workflow dispatch, or AWS mutation was performed.

## Current evidence

| Item | Status | Evidence |
| --- | --- | --- |
| Repository source | PASS | `kaku3030/stock-razor` is public; current main SHA is recorded above. |
| Windows device | PARTIAL | Desktop Commander listed `DESKTOP-2SLTODA` online, but its remaining call quota is 0%; this is not a successful shell or file operation. |
| Existing self-hosted runner | NOT_VERIFIED | The connected GitHub surface does not permit the Actions runners inventory endpoint. Current workflow/code search found no `runs-on: self-hosted` workflow reference. That does not prove the account has no registered runner. |
| Windows command/file access | BLOCKED_PENDING_LOCAL_BOOTSTRAP | No alternative Windows connection is installed or registered in this workspace. |
| Existing AWS secure MCP path | PARTIAL | Main contains `aws-ssm-ops.yml` actions for `secure_mcp_tunnel_deploy`, `secure_mcp_remote_e2e`, and a canonical read-only MCP E2E. This is an AWS-hosted read-only path; it does not connect to Windows. |
| Cloud autonomy | PARTIAL | The 120-minute workflow is manual, bounded, and test-allowlisted. It stores checkpoints in per-run Actions cache. Current cloud status does not expose an autonomy worker heartbeat or cross-run Feedback Hub persistence. |
| Safety gates | PASS | Context Manager currently keeps `LIVE_TRADE=false`, `PAPER_AUTO_READY=false`, `RADAR_ADMISSION=BLOCKED`, and `SOURCE_ARBITER_ADMISSION=BLOCKED`. |

## Route A: access design and bootstrap boundary

### Avoid registering a Windows runner to this public repository for general jobs

GitHub warns that self-hosted runners attached to public repositories can be exposed to dangerous code from fork pull requests when a workflow runs that code on the runner. This repository is public. Do not add a self-hosted label to `pull_request`, `pull_request_target`, issue, comment, or schedule workflows, and do not check out or execute fork-controlled refs on the Windows device.

A future runner pilot must use a restricted control surface: trusted `main` only, manually triggered, fixed task identifiers, no free-form shell/path inputs, one job at a time, no repository write token, and logs that omit hostnames, usernames, local paths, account IDs, and private service output. A separate private control repository or a private MCP bridge is the safer long-term owner. Keep runner registration tokens short-lived and enter them only on the Windows device; never put them in GitHub files, workflow inputs, PR comments, or ChatGPT.

### Reuse existing remote MCP components

Main already has the canonical read-only MCP server and an AWS secure MCP tunnel workflow. Reuse those rather than creating a second cloud MCP server. To reach Windows, the missing link is a private authenticated path between an allowlisted Windows MCP service and the existing cloud bridge. It must use outbound-only connectivity from Windows or a private overlay, bind no unauthenticated public listener, and expose a reviewed tool allowlist. A localhost URL alone cannot be called remotely.

Before enabling file or command tools, define the exact Windows working-directory allowlist, command allowlist, output redaction, max runtime/output, concurrency, cancellation behavior, audit receipt, and reconnect semantics. Keep these operations read-only until the specific write scope is separately reviewed. The local service must fail closed when the bridge, authentication, or identity check is unavailable.

### Required one-time local bootstrap and acceptance

The Windows user must perform the bootstrap once because registration requires a short-lived GitHub-generated token and local administrator/service setup. After the safe bootstrap package is ready, the only local action should be to open an elevated PowerShell window, run the reviewed script, and enter the one-time token locally. No credential will be sent through chat or committed.

Acceptance must capture private/sanitized evidence for: device identity match, PowerShell version, fixed read-only command execution, a file read from an explicitly allowlisted test directory, connection interruption, service reconnect, and timestamped local audit receipt. Do not publish device identity or private file contents to this public repository.

## Route B: durable autonomous engineering

Reuse the current autonomy loop, queue, incident memory, Feedback Hub implementation in PR #873, and AWS/Actions components. Do not create a parallel queue.

The current 120-minute loop checks exact main and the self-improvement registry, validates numeric resume IDs, restores only an exact cache key, honors a bounded stop check, writes a failure receipt, and has a two-task read-only test queue. This is useful scaffolding. It is not proof of durable job execution: Actions cache is a checkpoint transport, not the authoritative task database, and the current queue only runs tests.

Before long-running coding is enabled, require a durable Feedback Hub path, one task lease per task ID, idempotent recovery, bounded retries and budget, failure receipt, live stop/cancel validation, and a fresh-run/restart test proving that the exact task resumes without duplicate side effects. PR #873 contains relevant Feedback Hub integration work but remains unmerged; do not treat its proposed implementation as deployed or as proof of cloud persistence.

The existing scheduled V1 workflow creates sanitized audit-record PRs. It is not a coding agent. The DeepSeek+Aider coding pilot is manual and one-shot; no paid call is authorized by this preparation note.

## Next execution gates

1. Query the GitHub runner inventory from an authorized Actions administration surface; record exact runner labels and status without exposing secrets.
2. Decide the private runner/MCP control owner before installing anything on Windows.
3. Prepare and review the Windows bootstrap and fixed-tool bridge on an isolated branch; validate it on a Windows-hosted CI job.
4. At the first available local session, run the bootstrap once and complete the command, file-read, disconnect, and reconnect checks.
5. Separately trigger the existing AWS SSM read-only MCP E2E through an authorized workflow-dispatch surface and record its exact run ID/SHA.
6. Complete the Feedback Hub cross-run durability and idempotency test before claiming Route B PASS.

## References

- [GitHub: Adding self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners) — registration token expires after one hour; Windows service registration requires administrator privileges.
- [GitHub: Managing runner access](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access) — public repository runners carry fork-PR code-execution risk.
- Current implementation references: `.github/workflows/aws-ssm-ops.yml`, `.github/workflows/engineering-autonomy-120m.yml`, `engineering_autonomy/loop.py`, and PR #873.
