# Round25 OpenD 1-minute capture audit

Date: 2026-10-20 (Asia/Tokyo)  
Scope: local Windows OpenD historical bars, QFQ, requested regular trading hours. Raw captures remain on the user's Windows machine and are excluded from this repository.

## Result

OpenD returned genuine historical 1-minute bars for all six Round24 symbols. A separate local capture was copied into the ignored worktree directory `data/round24_s2_1m_opend_probe_20261020/`; the earlier AAPL/AMD capture was not overwritten because its SHA256 values differed.

| Symbol | Rows | Session dates | First bar | Last bar | OHLCV / timestamp checks |
|---|---:|---:|---|---|---|
| AAPL | 761,310 | 1,959 | 2019-01-02 09:31 | 2026-10-16 16:00 | Pass |
| AMD | 761,310 | 1,959 | 2019-01-02 09:31 | 2026-10-16 16:00 | Pass |
| COHR | 403,200 | 1,038 | 2022-08-29 09:31 | 2026-10-16 16:00 | **Fail: one OHLC envelope violation** |
| NVDA | 761,310 | 1,959 | 2019-01-02 09:31 | 2026-10-16 16:00 | Pass |
| QQQ | 761,310 | 1,959 | 2019-01-02 09:31 | 2026-10-16 16:00 | Pass |
| TSLA | 761,310 | 1,959 | 2019-01-02 09:31 | 2026-10-16 16:00 | Pass |

All six files had strictly increasing, unique timestamps, no intraday minute gaps, finite positive OHLC except the COHR row shown below, and nonnegative volume. Daily counts were 390 bars or 210 bars (no other count occurred); the audit did not cross-check whole-session coverage against an authoritative exchange calendar, and provider timezone/finality remain unverified.

## COHR provider anomaly

At `2025-02-11 09:31:00`, OpenD returned:

- open 91.67
- high 91.67
- low 91.67
- close 93.66
- volume 22

This violates `high >= max(open, close, low)`. A separate one-day OpenD QFQ/RTH request returned the same 390-bar day and the same invalid bar. The value was not edited, inferred, or replaced. COHR's 1-minute input therefore remains disqualified for a six-symbol S2 result until the source issue is resolved or the study is explicitly re-scoped.

## S2 decision

The repository's Round16 contract only states “Radar D1+1H+15m+5m+1m; closed-bar confirmations only.” It does not specify deterministic signal, confirmation, entry, or stop semantics. Round16–23 trade ledgers or a frozen S2 rule were not found in the Round24 branch tree or the retrieved prior project context. The proposed 5m/1m breakout proxy was withdrawn and is not part of this branch.

**No S2 backtest was run.** The existing Round24 report's contemporaneous “1m input absent” status was accurate when that run was generated; this audit supersedes the current data-availability assessment. A formal six-strategy comparison still requires the frozen S2 rule and resolution of the COHR input defect. Existing strategy, deployment, paper, and trading gates remain unchanged.

## Local evidence

- Raw CSVs and the row-level JSON quality manifest are local-only under  
  `C:\Users\77896\Documents\stock-razor-worktrees\round24-six-strategy-backtest-20261020\data\round24_s2_1m_opend_probe_20261020\`.
- The manifest is `round24_s2_1m_quality_audit.json`. No raw bars are included in this commit.
- The independently downloaded 1m CSVs do not replace the earlier AAPL/AMD capture.

