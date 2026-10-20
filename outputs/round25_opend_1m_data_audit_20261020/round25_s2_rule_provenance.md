# Round25 S2 strategy-rule provenance

Date: 2026-10-20 (Asia/Tokyo)  
Scope: read-only source and artifact inspection of the Round16 and Round24 research refs. No backtest was run and no strategy rule was inferred.

## Findings

- Round16 commit `06e9c82985a5220c9efd27eb18739a6811f518f9` contains the contract `docs/research/round16-six-strategy-regime-contract.md`. Its S2 entry is only: “Radar D1+1H+15m+5m+1m; closed-bar confirmations only.” It gives no deterministic trigger, entry timing/price, exit/stop/target, risk sizing, concurrency, or execution timeframe.
- Round11 source `tools/research/round11_radar_research.py` lists `D_D1_1H_15m_5m_1m` in `PROTOCOLS`, but emits a protocol-matrix row with status `NOT_VERIFIED` and reason `1m capture missing`. There is no D signal builder or D trade replay in that source. The executable replay is inherited Round10 Protocol II/III, which does not consume 1m.
- Round24 commit `3c5ff9805aa3f660e2085fab14b101ff18ad1000` has `_build_arms()` for S1 and S3–S6 only; its S2 status is blocked and it calls `qualify_s2_coverage()` only. No S2 signal or trade generation is implemented there.
- Round24's “genuine historical 1m bars absent” message reflects its run-time inputs and is superseded as a current data-availability statement by the Round25 OpenD audit. The new six-symbol capture is genuine local 1m data, with one unrepaired COHR OHLC-envelope violation at `2025-02-11 09:31:00`.
- Project-context retrieval and the Round24 branch tree search found no Round16–23 frozen S2 transaction ledger or deterministic S2 rules. The previously proposed 5m/1m breakout-volume proxy was withdrawn and is not used.

## Decision

S2 remains `BLOCKED` for two independent reasons: (1) no reproducible, frozen S2 rule contract exists in the inspected assets; (2) the six-symbol 1m set contains one invalid COHR bar. Do not label a reconstructed or guessed rule as the user's S2. Any five-symbol study would be a separately scoped result, not a six-symbol comparison.

## Existing Round24 results retained

Round24's S1 and S3–S6 outputs are preserved as generated. Its 10 bps/side table, 5/10/20 bps cost stress, OOS table, buy-and-hold benchmark, signal/trade ledgers, daily equity and source manifest remain at `outputs/round24_six_strategy_backtest_20261020/`. They have not been regenerated from the new 1m capture.

Safety gates remain unchanged: `RADAR_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO`, `TRADE_EXECUTION=NO`.
