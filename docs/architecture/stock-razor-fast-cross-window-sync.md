# STOCK RAZOR V1.4 | Fast cross-window context sync

## Scope

Keep the existing GitHub main as canonical engineering rules and the existing AWS Context Manager as the read-only project event state. Do not build another competing store. New windows must fetch rather than assume dormant ChatGPT conversations are pushed updates.

## Trigger and fetch

When a project chat first mentions 交易 / 雷达 / 美股 / A股 / OpenD / TickFlow / 策略 / 回测 / 云端 / STOCK RAZOR, classify the sanitized utterance using scripts/stock_razor_fast_sync.py --route. A dedicated project chat with a short 继续 also triggers recovery. Inspect actual GitHub main SHA and fetch AGENTS.md, the self-improvement SKILL, failure-registry.json and associations.json at that same SHA. Read both STOCK RAZOR US/CN MCP __CONTEXT_MANAGER_STATE__ sentinels; check domain timestamp, TTL and provenance. Read latest OWNER-authored tagged sync comments on PR #924 relevant to the topic. The last event in any given Context Manager domain is not proof that all topics are complete.

## Publish one important project decision per comment

Only owner kaku3030 may publish. Comment on PR #924 exactly:

STOCK_RAZOR_SYNC_V1

{"topic":"engineering","state":"IN_PROGRESS","summary":"最新跨窗口快速同步机制已进入工程验证；不代表云端运行或交易业务验收成功","evidence_url":"https://github.com/kaku3030/stock-razor/pull/924","source_sha":"0000000000000000000000000000000000000000"}

Replace the example SHA with the actual 40 lowercase hex commit and evidence URL with the exact project evidence. Values for topic: us, cn, strategy, engineering, portfolio, policy. Values for state: DECIDED, IN_PROGRESS, BLOCKED, VERIFIED, RESEARCH_ONLY. A VERIFIED result requires independent actual evidence, not merely CI green or code merge. Summary must be short (12–480 characters), non-sensitive and project-only.

GitHub issue_comment workflow validates project, issue #924, commenter is OWNER, comment shape, fields, SHA, evidence URL and timestamp before assuming the existing AWS GitHub OIDC role. It writes a sanitized payload through the existing SSM fixed-host Context Manager command, using an event id tied to the GitHub comment ID. Event projection TTL is 3 days; the original public GitHub issue comment persists as historical evidence.

**Privacy:** Never publish specific private holdings, account IDs, order intentions, client personal details, raw K-lines/logs or credentials in GitHub comments. A portfolio query can trigger private read-only state lookup but cannot publish private user data.

## Five evidence stages

1. Published: owner GitHub comment ID and created_at.
2. Workflow: GitHub issue_comment Actions run ID and status.
3. Stored: SSM command outcome RECORDED/DUPLICATE, without raw payload leakage.
4. Readable: independent US/CN STOCK RAZOR MCP sentinel readback of the same event ID.
5. Actual new-window retrieval: relevant first message actively retrieved the newest matching-topic event.

Measure creation-to-run-to-SSM-to-read latency with actual UTC timestamps. GitHub Actions is best effort, **not an instant delivery SLA**. A repo skill cannot insert messages into a different dormant ChatGPT thread. Missing sources or stale evidence must return SYNC_NOT_VERIFIED / STALE; never imply a trading gate PASS. All market, Paper and live trading gates remain unchanged.

Rollback: disable this dedicated workflow and revert V1.4 files; the existing GitHub PR/CI Context Manager feed is untouched.
