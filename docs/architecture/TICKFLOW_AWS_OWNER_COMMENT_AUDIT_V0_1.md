# TickFlow owner-comment AWS read-only audit (V0.1)

## Goal

The stock-razor repository owner can request an **existing bounded AWS research audit** without a personal computer. Post the exact command `/stock-razor tickflow-audit read-only` as a **new GitHub PR conversation comment on merged PR #658**. The action uses GitHub Actions and AWS Tokyo SSM under the existing GitHub Ops role; no additional IAM scope, keys or provider-worker subscription is created.

This is complementary to existing two weekday UTC cron audits and manual `workflow_dispatch`. Cron runs can be delayed or skipped; neither cron nor on-demand probes guarantee exchange-bar closure or real-time qualification.

## Fail-closed authorization

Both GitHub's immutable workflow job condition and the independent `authorize_cloud_ops_audit_comment.py` validator require the authenticated repository owner, an actual PR issue-comment event, positive comment ID, exact PR #658, exact command bytes, and OWNER author association. The existing PR #665 `/stock-razor aws-audit read-only` command retains its old mapping. Wrong PR/command combinations are not interchangeable.

For all eligible events, the workflow checks out immutable `github.sha`, confirms it is the latest protected `main` before AWS OIDC, and checks latest `main` again immediately before its fixed SSM operation. Stale events, forged identities, lookup failures or move races fail closed. The AWS command uses the existing immutable audit script and produces sanitized categorical results only.

## GitHub queue isolation

`concurrency` is scoped to the *qualified audit job*, not to the entire workflow event. Public comments on other PRs and untrusted comments on #658 still generate a GitHub event but their jobs skip the authorization predicate **before** acquiring the audit concurrency lock. This prevents untrusted/irrelevant comment events from replacing a queued owner-authorized audit when a protected-main push audit is already running. Legitimate audits still serialize on the same fixed AWS target; GitHub queue behavior can supersede older pending *legitimate* requests, so each requested run's exact result must be inspected.

## Interpretation and rollback

The audit can confirm EC2 systemd presence, read-only MCP cache/history, two snapshots 65s apart, independent Tencent crosscheck and quarantined 15m/60m OHLC diagnostics. `historical_research_usable=true` is **not** real-time admission. `source_arbiter_admission=BLOCKED`, `radar_admission=BLOCKED`, `paper_auto_ready=NO`, `live_trade=NO`, `trade_execution=NO` remain fixed.

A successful GitHub workflow means an inspection happened, not that the feed, Radar or trading is qualified. To roll back, revert the owner-comment workflow event and the second command mapping; both cron and manual research audits remain.
