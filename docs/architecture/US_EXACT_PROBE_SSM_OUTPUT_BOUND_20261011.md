# Fix: US cloud exact probe truncated by AWS SSM stdout ceiling

The read-only AWS workflow run 38146676996 on 2026-10-11 failed in the
GitHub runner's JSON parse with JSONDecodeError at column 23981, consistent
with AWS SSM GetCommandInvocation StandardOutputContent truncation around
24 KiB. The Python producer had written large nested heartbeat, Radar and
sample histories, which were not needed by the governance gate.

The workflow now supplies --ssm-summary-only to the immutable, SHA256-pinned
Python probe. It emits only bounded allowlisted gate labels for exact runtime
SHA, continuous sequence, currentness, and 15m/60m closure, plus three
immutable BLOCKED/NO governance fields. No raw heartbeat, account, cache,
prices, Radar payloads or private data are included in stdout. A direct
safety-envelope inconsistency fails the run instead of papering over it.

The original full JSON mode is preserved for deliberate offline diagnostics;
the production SSM workflow exclusively uses the compact report. This PR
does not deploy or restart AWS services, mutate OpenD subscriptions, invoke
paid TickFlow or send any orders.

A *new* post-merge cloud read-only workflow rerun is required to establish
AWS success. CI tests only validate output size and offline parser behavior.

RADAR_ADMISSION=BLOCKED; SOURCE_ARBITER_ADMISSION=BLOCKED;
PAPER_AUTO_READY=NO; LIVE_TRADE=NO.
