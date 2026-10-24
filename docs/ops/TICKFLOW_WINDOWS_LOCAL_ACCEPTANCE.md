# Windows TickFlow local acceptance — Hybrid V1.0

Windows owns TickFlow; AWS owns OpenD. This procedure does not develop OpenD,
strategy research, order entry or source admission. Older two-endpoint TickFlow
acceptance requirements are superseded for this local route. Historical AWS
records remain evidence of their original scope, not a local prerequisite.

## Confirmed deployment drift

On 2026-10-24, the actual Windows scheduled task still used an October 15
copied auditor (SHA256 819fb5b12966c22c47b68535f197b65e2fce6b0300228ec3b9a33d599633e2a7)
and a wrapper expecting eight records: two ETFs, four periods, no 1m.
Current main's matrix is four ETFs by five periods (20). Task exit zero was
not evidence of the new matrix. The old wrapper had no source revision check
and skipped closed windows without a receipt.

The installed package is official tickflow 0.1.25, a Python REST/stream client.
Its distribution contains no NativeSDK pyd/dll files. No native binary session,
server subscription acknowledgement, real disconnect/reconnect or complete
five-period trading day was proven by that inspection. Do not relabel REST
polling or a synthetic timeout recovery as NativeSDK production acceptance.

## Install and rollback

Use an isolated, clean, committed checkout and its exact 40-character SHA:

    powershell -NoProfile -File scripts/install_tickflow_windows_watch.ps1 -ExpectedSha <SHA>

The installer requires the already-installed Python, tickflow 0.1.25,
pywin32, exchange_calendars, timezone data and existing Credential Manager
credential. It installs nothing and prints no credential values. It backs up
the old task XML and copied files under the existing local private directory.
Restore those files and import the saved task XML to roll back.

The existing task name STOCK_RAZOR_TickFlow_Desktop_30m_ReadOnly is retained to
avoid a duplicate collector. Its new cadence is two minutes, IgnoreNew,
StartWhenAvailable, bounded four-minute task lifetime, three scheduler retries
one minute apart. Each child has a 190-second deadline, each SDK request an
eight-second timeout, no SDK retries; a new run creates a new SDK context and
revalidates all frames. This is bounded polling recovery, not proof of stream
resubscription or of missing-data backfill.

The task uses the signed-in user's limited interactive token, no stored password.
A powered-off/logged-out device is not observed. Sleep prevents collection;
StartWhenAvailable permits a fresh poll after wake, but does not reconstruct
missed live observations or prove sleep recovery. It does not wake the computer
at night. The local calendar gates XSHG sessions and Shanghai 09:30–11:35,
13:00–15:35; early/late observation windows include publication grace. Unknown
calendar fails closed. No weekend provider calls.

## Receipt contract

Every complete poll must contain exactly the current four-symbol five-period
matrix, with TickFlow-only lineage, SDK transport/version, data label time,
observation time, request milliseconds, bar-label age, strict and research
quality counts, and original close/volume/OHLCV hashes. Hashes prove comparison
of local observations only, not authenticated provider provenance.

Intraday labels are BAR_END; D1 is DATE_LABEL. A row may receive operational
research closure only when its immediate next legal same-day grid label is
present. The last received intraday row remains unproven; current-day D1 stays
quarantined. Historical daily labels are research only. Provider correction
remains possible; immutable finality is NOT_VERIFIED. Label age is not network
latency or quote callback lag. Field hashes detect revisions without rounding
or changing vendor values; volume units remain unverified.

Extra off-grid labels, reordered/duplicate rows, missing due boundaries,
nonfinite data, wrong source, incomplete matrices, deployment hash drift,
timeout or unknown child output remain blocked. An empty due grid is never a
PASS. Precision-tolerated research rows never become strict valid prices.

Private files under %LOCALAPPDATA%/StockRazor/TickFlowHalfHour:
- deployment.json: source SHA and exact copied-file hashes.
- latest-attempt.json: latest health, including closed/unknown calendar windows.
- latest-poll.json: latest attempted SDK poll; failures replace prior PASS.
- evidence/<Shanghai-date>/*.json: individual original-value hash receipts,
  retained for five observed dates. Do not upload the private directory.

Production acceptance stays NOT_VERIFIED; source/Radar BLOCKED; paper/live false.
This receipt is an observation contract, not a canonical tradable-price feed.

## Next real session

Candidate next session is Monday 2026-10-26, subject to installed XSHG calendar.
Keep Windows signed in, awake and online for JST 10:30–12:30 and 14:00–16:00;
the watcher continues through JST16:35 for final publication observations.
At end of day independently check all 20 frame receipts, 240/48/16/4 intraday
due labels, D1 prior-date semantics, sample gaps, changes and regressions.
Do not reuse the October23 eight-frame log as five-period evidence.

Still required: actual quote subscription evidence if NativeSDK streaming is
the acceptance target; full live trading-day observation, controlled disconnect,
process termination/restart and wake/reboot recovery with source continuity;
independent Radar consumer readback. Offline tests, task registration and
weekend skip are separate evidence tiers. No gate may be opened by these tests.


## Incremental pre-session fault evidence — 2026-10-24

The actual installed task was independently re-read at source
29add70457c13de66d379527cc824685d6080236: both file hashes match, PT2M,
IgnoreNew, StartWhenAvailable=true, restart count3, Ready, latest result0.
A subsequent automatic weekend execution recorded CLOSED/NOT_OBSERVED and
zero provider requests. No task was added, replaced or rescheduled in this phase.

Five NEW Windows tests in tests/test_tickflow_local_fault_injection.py passed
in4.19seconds. The previous57tests were not rerun. The new tests use real local
TCP sockets and actual installed official tickflow0.1.25 with a synthetic key,
explicit loopback endpoint, and an external-address prohibition:
- response dropped before headers, read timeout, and HTTP429 each raise after
  exactly one request with max_retries0; a later socket request succeeds;
- disconnect surfaces as raw httpx.RemoteProtocolError rather than necessarily
  sdk.ConnectionError. The existing auditor's public main entry already
  catches it, emits only the safe class and BLOCKED, then a new SDK context
  revalidates after the local endpoint recovers;
- a separate Windows Python process exits hard with code71 after writing an
  incomplete staging file. The published sequence1 remains valid; a fresh
  process reads it and atomically publishes sequence2/REVALIDATION_REQUIRED.
  This proves process/filesystem behavior under a synthetic interruption,
  not restart of a live provider collector or restart of Windows.

The tests use only127.0.0.1, never Credential Manager or provider endpoints,
never system firewall changes, real sleep/reboot, or live market evidence.
No production-code defect was found in this bounded experiment; therefore
there is no SDK/site-package patch, extra dependency, or production redeploy.
These optional SDK tests skip where the pinned package is absent; the Windows
five-pass observation is separate from CI skip/pass counts.

Reproduce only the incremental experiment:

    python -m pytest -q tests/test_tickflow_local_fault_injection.py --basetemp=<fresh-private-temp-dir>

Remaining acceptance must use the actual Monday session and provider transport:
full day20frame evidence; actual subscription/stream ownership; disconnect and
resubscription; sleep and reboot with interval accounting; units and independent
Radar consumer validation. A synthetic socket or hard process exit cannot
substitute for any of those production observations. All gates stay blocked.
