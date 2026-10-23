# TickFlow private research evidence

The existing isolated collector reuses each successful five-period cache observation
without additional provider calls. On weekdays its first validated observation at
or after15:02 Shanghai and before20:00 creates `baseline.json`; its first validated
observation at/after20:00 creates `after20.json`. Both reside under the existing
systemd private state directory `/var/lib/stock-razor-cn-tickflow/evidence/YYYY-MM-DD/`.
Files are0600, directories0700, atomic create-only, never overwritten. Each file is
bounded to2MB and the store to64MB; quota exhaustion blocks new evidence without
removing old evidence or stopping the market cache. No automatic pruning.

Each manifest contains four ETFs ×1m/5m/15m/60m/1d, labels, per-field hashes,
source code SHA, observation time, process-local sequence and declared endpoint.
It stores no raw prices. Intraday due grids must be complete and D1 must contain
60 prior dates. Hashes detect file/field differences; they do not authenticate a
physical endpoint. Process-local sequence may reset after restart; revision
comparison requires advancing observation time at the same code revision/day.

Read the already connected `get_cn_market_data(symbol="TICKFLOW:EVIDENCE")` for a
bounded status and comparison counts only. No SDK request, hashes or raw values
are exported. The normal tool schema and other sentinel routes remain unchanged.
Evidence I/O/validation errors are explicit and never become data admission.

`BASELINE_RECORDED_AWAITING_AFTER20` is pending, not a completed correction audit.
`baseline_timing=LATE_BASELINE_LIMITED` means baseline after15:15: earlier revisions
cannot be reconstructed. `POSTCLOSE_COMPARISON_RECORDED` must be read together with
its comparison status; `REVISION_OBSERVED` reports differences and
`NO_REVISION_OBSERVED_NOT_FINAL` only reports no difference between two samples.
`BASELINE_MISSING` and `POSTCLOSE_COMPARISON_BLOCKED` are not passing results.
An after20 sample follows vendor guidance; it is not a guaranteed final seal.
Deploying after20 cannot create that day's missing closing baseline.

## Windows capture and offline comparison

Default execution does not read credentials, instantiate the SDK or make requests:

```powershell
python -m scripts.capture_tickflow_endpoint_evidence
```

Once the Windows device is online, use an isolated clean checkout of the exact
protected-main revision, existing Windows credential storage and tickflow0.1.25.
The following explicit action performs one bounded existing four-ETF five-period
SDK observation, with no retries, subscription or order calls. Choose a new private
output filename each time; existing files cannot be overwritten. Execute-mode output marks SDK activity explicitly and leaves provider request
count unknown; `provider_requests=0` on stored manifests/comparison refers only
to the offline evidence operation. Capture sequence
is a local counter, not a provider sequence. `--expected-sha` is mandatory in execute
mode and must match the checkout's full40-character SHA.

```powershell
python -m scripts.capture_tickflow_endpoint_evidence --execute --expected-sha FULL_SHA --sequence 1 --output C:\PRIVATE_DIRECTORY\windows-first.json
```

Compare independently obtained private manifests offline (no SDK/credential access):

```powershell
python -m scripts.capture_tickflow_endpoint_evidence --compare C:\PRIVATE_DIRECTORY\aws-first.json C:\PRIVATE_DIRECTORY\windows-first.json --dual-endpoint
```

Dual comparison requires declared distinct AWS/Windows endpoints, identical day
and code SHA, capture clocks within30seconds, no future capture and validated full
due grids. Keep both original files private and independently verify where each
was captured; copying or relabeling one file is not proof of dual provenance. The
collector's stored closing baseline is not a current paired capture hours later.
Fresh AWS capture/secure private retrieval remains an operator prerequisite for
actual paired acceptance; the public MCP intentionally does not export manifests.

Return codes:0 for a valid observation/comparison (including observed differences),
2 for invalid/blocked input or existing capture output. Always inspect status and
counts, not only the exit code. For same-endpoint revision comparisons omit
`--dual-endpoint`. No numerical tolerance is applied to hash differences.

All outputs remain research-only, `provenance_verified=false`, finality NOT_VERIFIED,
source/Radar BLOCKED, paper_auto_ready=false and live_trade=false. Matching evidence
alone does not qualify strict OHLC, indicator history, replay, strategy or trading.
This operational document has no paired English/Chinese document to synchronize.

## Compact postclose pairing without moving private manifests

`get_cn_market_data(symbol="TICKFLOW:PAIR")` reads one existing AWS cache observation,
revalidates all20frames and returns `pairing_summary`:20 fingerprints and row counts,
source SHA, capture clock and declared endpoint. No labels, prices, field hashes,
provider request or evidence-file write. The source must be at most330seconds old
and after15:02 Shanghai on a weekday; this is intentionally postclose-only.

Windows capture may add `--summary` to print the same compact receipt while keeping
its full manifest private. A manifest captured by an earlier protected revision
can be summarized offline with the newer helper:

```powershell
python -m scripts.capture_tickflow_endpoint_evidence --summarize-manifest C:\PRIVATE_DIRECTORY\windows-first.json
```

The source SHA stays that of the original SDK capture, not the postprocessing
helper. Keep the SDK checkout at the actual AWS collector revision for a pairing;
use a separate current-main checkout for offline summarization when necessary.
Never relabel or rewrite a manifest to hide a revision mismatch. Execute-mode
capture on the newer helper also rejects a dirty checkout before SDK activity.

A caller can compare two `pairing_summary` objects with
`compare_pairing_summaries(aws_receipt, windows_receipt)`. For private summary JSON
files, use `--compare FIRST SECOND --compare-summaries`. This mode performs no SDK
activity. Both captures must have the same day/source SHA, distinct endpoints,
clock skew at most30seconds, age at most330seconds and no future clock beyond5s.
The result reports only the number of different frames. A matching hash receipt
is observational research evidence; independent actual endpoint calls remain
necessary to verify physical capture. It does not establish provider finality.

MCP/helper-only changes do not justify restarting the collector during an ongoing
baseline/after20 pair: retain the existing collector SHA so both immutable samples
can be compared. A different source SHA yields explicit EVIDENCE_INVALID rather
than silently accepting mixed revisions or overwriting the baseline.

## Reproducible amount/volume hypothesis diagnostics

`get_cn_market_data(symbol="TICKFLOW:UNITS")` uses the same single bounded cache
read and20-frame validation as the pairing route. It reports counts only under
`formula_id=AMOUNT_OHLC_VOLUME_ENVELOPE_DECIMAL_V1`; no price, raw quantity, amount
or K-line label is returned. It does not prove a unit contract or enable VWAP.

For each validated row with positive volume V and positive amount A, the exact
scale S hypothesis tests `(low-0.00001)*V*S <= A <= (high+0.00001)*V*S`.
Report S=1 and S=100 separately. For rows outside the exact S=100 range, the
quantity-envelope test with delta D is
`(low-0.00001)*max(0,V-D)*100 <= A <= (high+0.00001)*(V+D)*100`,
for D=0.5 and D=1. D is measured in original raw volume units. All comparisons
use Decimal values from original number strings and precision50. This is not
the same as allowing one price unit of VWAP error. The envelope is a diagnostic
hypothesis, not a permitted mutation or acceptance tolerance.

Zero volume, zero amount, missing amount and fractional raw volume have distinct
counters. Negative, nonfinite or unbounded values fail closed. Scope is today's
validated intraday labels plus prior60D1 dates, matching the private manifest.
Every output retains units_contract NOT_VERIFIED, scale100 HYPOTHESIS_ONLY and
all source/Radar/paper/live gates closed. Do not infer ETF units from numerical
fit or official stock examples alone. A range exception is not by itself a proven
provider defect. Persist the formula ID with all future counter comparisons.
