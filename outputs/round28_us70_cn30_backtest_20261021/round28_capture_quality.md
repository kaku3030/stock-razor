# Round28 local capture quality and provenance

**Audit date:** 2026-10-21  
**Requested window:** 2019-01-01 to 2026-10-16  
**Frames:** D1, 1H, 15m, 5m, 1m  
**Source:** local Futu/OpenD only; QFQ, RTH; raw and effective CSVs stay outside Git.

## Coverage added

- Captures were requested for 32 additional U.S. candidate symbols. The effective dataset contains 160 files (32 symbols ? 5 timeframes). Together with the 28-symbol Round27 baseline, the candidate cohort now has complete five-frame coverage for 60/70 U.S. names.
- The 10 additional U.S. names still missing are `ABNB, AXON, MPWR, NXPI, PDD, ROP, SHOP, SNPS, VRTX, WDC`. OpenD history quota is exhausted (100 used, 0 remaining).
- A local OpenD permission check for `600519.SH`, `300750.SZ`, `601318.SH`, and `600036.SH` returned ??????A?????????A?????????? for all requested timeframes. No A-share data was returned. No paid TickFlow history route or other paid data call was made.

## Data-quality handling

- Raw captures and quarantined files were left unchanged. The effective-copy builder identifies any invalid OHLCV row in any timeframe for a symbol, excludes the entire affected calendar date from all five timeframes for that symbol, then revalidates effective rows.
- Audit found 78 invalid OHLCV rows across 10 U.S. symbols and 61 affected symbol-calendar dates. These dates were excluded from every timeframe for the affected symbol; all 160 effective files remain present. The complete date-by-date and per-file SHA-256 record is in `round28_effective_capture_manifest.json`.
- Affected symbol-date counts: ADI 1, BKNG 1, CEG 4, CTAS 3, DDOG 1, INTU 2, ISRG 1, LRCX 1, PANW 46, REGN 1. PANW accounts for most exclusions and should receive extra scrutiny before any future backtest.
- The capture manifest preserves per-timeframe request outcomes and errors. The effective manifest records source and output hashes, row counts, date ranges and exclusions. These manifests include local Windows source paths for reproducibility on the connected machine.

## Gate status and limits

- Present files: 300/500 (60.0%): U.S. 300/350; A-shares 0/150.
- Current blockers: remaining U.S. history quota, missing A-share OpenD entitlement and local TickFlow cache, unverified point-in-time universe membership, and unavailable official frozen S2 rule.
- This artifact certifies capture/cleaning provenance only. It does not establish corporate-action completeness, point-in-time constituent membership, fill realism, strategy performance or eligibility for strategy promotion. No Round28 strategy backtest, cost stress test, or out-of-sample result is claimed.

## Artifacts

- `round28_local_opend_capture_manifest.json` ? request outcomes and capture metadata.
- `round28_effective_capture_manifest.json` ? effective file hashes, row counts, dates and exclusions.
- `round28_data_gate_status.json` ? per-symbol/timeframe coverage and blockers.
- Raw/effective CSV data root (local, ignored by Git): `C:\Users\77896\Documents\stock-razor-opend-captures\round28_us70_local_opend_20261021`.
