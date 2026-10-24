# STOCK RAZOR | Work session reliability and continuity V5.2

Decision date: 2026-10-24 JST. Scope: all Work execution chats; incident first observed repeatedly in Work 01.

## Incident signature
`WORK_CHAT_MESSAGE_DISAPPEARED`: user sends a chat message and text vanishes; some previously visible turns also disappear. Do **not** conflate with a running agent taking long to reply. ChatGPT UI/history behavior is outside the repository's control, so no repository change is a claimed UI bug fix.

## Immediate user-facing handling
1. **Preserve** original conversation URL and running task. Never delete or cancel a running task only because UI messages disappeared.
2. Save future critical prompts in a local note *before sending* until stability is proven; verify the sent turn persists after refreshing/reopening (avoid assuming delivery).
3. Try opening the same conversation in a different browser/private session or device. Check ChatGPT status, app updates, extensions and network; verify correct account/workspace and search/archive view for older missing chats.
4. If persistent, report via OpenAI Support with timestamps/JST, conversation URL, device/browser/app version and sanitized screen captures. HAR/console trace only when requested and after redacting session tokens, credentials, portfolio and private content.
5. Where necessary, use a **successor** Work 01 window, but first verify prior job/branch is not actively writing or deploying. Never allow concurrent ownership of the same working tree, PR or production deployment.

## Engineering continuity invariant
- Chat history is **not** the sole source of truth. Work must persist sanitized incremental checkpoints at meaningful durable transitions: `route | task_id | owner | current_main_sha | work_branch | head_sha | deployed_sha | last_verified_step | tests | runtime_evidence_links | blocker_signature | next_action | timestamp`.
- Use existing `AGENTS.md` / Context Manager / Feedback Hub mechanisms; do not add a competing synchronization system. Do not dump private chats, private portfolio, access tokens, secrets or raw logs to public GitHub.
- A successor begins with the latest protected main SHA and same-SHA agent rules, reads only relevant route checkpoint, PR/CI and runtime evidence, marks stale/unverified data, and resumes from last **verified** step, not the last asserted step.
- If a message vanishes, do not conclude the instruction was applied; confirm via persisted engineering side effects. Avoid blindly resending potentially non-idempotent commands (especially deploy/shutdown/paid calls).
- Completion means actual acceptance, not that the UI message appeared. If all chat access is lost, stop unsafe mutations and preserve recoverable repo state.
- Main Control may hand back one short successor prompt, but shall not rename chats.

## Reporting and escalation
`UI_STATUS | TASK_STATUS | LAST_VERIFIED_SHA | EVIDENCE | DUPLICATE_WRITE_RISK | NEXT_ACTION`.
UI loss alone is not a reason to downgrade data-quality/trading gates. ChatGPT client defects cannot be definitively repaired by the STOCK RAZOR engineering team; retain official support escalation separately.

## Model guidance
Current Pro preference: GPT-6.1 Sol High for critical engineering continuation; medium/lower tier for status recovery and summarization when available. Do not interrupt an active correct task just to change model.
