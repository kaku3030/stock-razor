# TickFlow Expert WebSocket missing optional dependency — 2026-10-12

## Real-market observation

- AWS Premium REST quoted prices, 1m/5m/15m/30m/60m K-line methods
  and depth all reported `COMPLETED` under the user's ¥199/month
  Expert subscription. That is SDK REST transport capability only.
- During the China lunch session, AWS bounded 10-second WebSocket
  run #38204799914 reported local subscription and connect *calls*
  `PASS`, but **0 callbacks**.
- During the actual China afternoon trading session, AWS bounded
  30-second WebSocket run #38206135825 again reported `PASS`
  local method calls and **0 callbacks**, despite the independent
  Tencent A-share feed publishing the developing 13:15 bar.
- The official TickFlow SDK `0.1.25` declares WebSocket support as
  `realtime = ["websockets>=13.0"]` in its project's
  `pyproject.toml` (tickflow-org/tickflow), but STOCK RAZOR's
  isolated AWS requirements installed only `tickflow==0.1.25`.
  This means the dedicated venv does **not intentionally install
  the optional WebSocket dependency**. An error inside the daemon
  thread after `connect(block=False)` may not reach the SDK's
  `on_error` callback, so `connection_call=PASS` does **not**
  imply a live transport. This is a concrete packaging flaw; the
  precise cause of the empty streams still requires a fresh live run.

## Minimal fix

- Install the official `tickflow[realtime]==0.1.25` extra in
  `ops/requirements/tickflow-isolated-v0.1.txt`, pinning its
  `websockets==15.0.1` dependency. No unreviewed SDK major upgrade.
- Before any AWS credential fetch or provider call in Premium
  `ws_seconds > 0` runs, import `websockets` in the actual private
  Python venv and verify its pinned package version. Fail with
  fixed diagnostic `TICKFLOW_WS_DEPENDENCY=UNAVAILABLE` and a
  sanitized bootstrap stage if missing.
- Also guard the standalone official SDK probe before initializing
  the client. Return `BLOCKED` instead of misleadingly reporting
  a legitimate market-session no-event WebSocket observation when
  `websockets` is missing.
- Keep explicit `quote_only=true` REST probes independent from this
  optional WS dependency check. Isolated fake-client tests are
  unaffected, since they make zero provider calls.

## Still not proven

Dependency installation is necessary, not sufficient. The next
operator-authorized bounded active-session run must verify real
provider handshake/connectivity, and count **post-initial timestamp
updates** instead of cached first snapshot candidates. No provider
subscription acknowledgement is currently available in the official
sync SDK surface. Require verified source timestamps, continuous
update rate, exchange-session semantics, 15m/60m bar closure and
independent Tencent/东方财富 comparison before any production
admission.

No AWS restart, real API requests, live WebSocket subscription,
subscription configuration mutations or broker orders occur on PR
merge. `PAPER_AUTO_READY=NO`, `RADAR_ADMISSION=BLOCKED`,
`SOURCE_ARBITER_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`.
