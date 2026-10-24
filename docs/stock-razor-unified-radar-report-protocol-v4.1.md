# STOCK RAZOR — Unified Market Data & Radar Report Protocol V4.1

Status: proposed; applies to A-share and US radar windows and MAIN CONTROL after review.
Date: 2026-10-19. This document does not authorize trading, deployment, paid calls, or relaxation of gates.

## 1. Provider exclusivity and dual-end validation
- A shares: TickFlow only, Windows NativeSDK and AWS TickFlow.
- US: OpenD only, Windows OpenD and AWS OpenD.
- No alternative market-data providers, including automatic fallbacks. Policy/news sources may inform catalysts but never replace market quotes.
- Both endpoints MUST request **1m, 5m, 15m, 1H, D1** per symbol, with per-endpoint/per-timeframe independent verdicts.
- Explicitly record market session (including A-share midday break, US pre/after-hours and DST), timezone, provider permissions, last candle timestamp, freshness, request duration, closed/unclosed candle status, OHLC validity, volume validity, bar continuity and dual-end agreement.
- Cached/historical bars must never be labeled real-time. Incomplete/unclosed candles are not confirmed signals.
- Missing, malformed, stale or conflicting data => NOT_VERIFIED/BLOCKED for affected signal; never fabricate, silently substitute or declare PASS.

## 2. Mandatory report order
1. Data provenance, dual-end five-timeframe acceptance, and performance.
2. Actual holdings first (symbol, verified quantity/as-of source, D1/1H/15m/5m/1m assessment, risk and conditions). Keep holdings separate from watchlist. If holdings not verified, label user-reported and time-stamp.
3. New opportunities (ranked 3–5 only when validated, with sector relative strength, price/volume, policy catalysts and evidence; otherwise explicitly no qualified candidates).
4. Conditional trade plans (entry trigger, invalidation, stop, target, risk/reward, position/risk budget, expiration); no execution.
5. Engineering exceptions, mainline feedback reference, and total response duration.

## 3. Radar decision policy
- D1 trend → 1H structure → 15m setup → 5m trigger → 1m execution refinement. Never infer confirmation from an open candle.
- Prefer strong pullback near support with renewed strength over chasing extension.
- Validate price/volume, cross-timeframe conflicts and sector-relative strength; downgrade conflicting signals.
- Prefer prospective reward:risk >= 2:1 where supported; calculate risk from stop distance before size, begin small.
- Distinguish watch-only, conditional, verified and blocked signals. Policy catalysts are research context, not standalone trade signals.
- Preserve replayable signal inputs, timestamp, rule version, decision rationale and later outcomes without lookahead.

## 4. Performance and audit fields
For each request record received_at, report_completed_at and measured elapsed milliseconds for: Windows fetch, AWS fetch, validation, technical analysis, opportunity/radar scan, report generation and end-to-end response. Also record request count, timeout/error codes, candle delay and freshness thresholds. **120 seconds end-to-end is a target, not an asserted result.** If unmeasured, write NOT_MEASURED rather than estimate.
- Report provider name, endpoint, market session, symbol, timeframe, candle time/timezone, closed flag, OHLC/volume and continuity verdict, latency, elapsed_ms, deployment SHA, code SHA, cache/source provenance and acceptance verdict.
- Report actual holdings before watchlist; no stale portfolio assumptions.

## 5. Fail-closed feedback loop
- Search existing GitHub issues/PRs and Feedback Hub before opening duplicates. For new defects include minimal sanitized evidence, reproduction, affected symbols/timeframes/endpoints, severity, code/deploy SHAs, owner, fix status and retest evidence.
- Do not leak credentials or account data. Distinguish created feedback from verified repair.
- Never auto-trade, enable live execution, admit blocked radar signals, bypass risk gates, auto-merge, or production-deploy merely because a report or individual endpoint passes.
- Explicit default: LIVE_TRADE=NO; TRADE_EXECUTION=NO; RADAR_ADMISSION=BLOCKED until separately authorized and verified.

## 6. Quality metrics
Track data acceptance rate, false-alert rate, signal hit rate, realized R multiple, maximum drawdown, report response latency, missed scans and replay integrity. Performance improvements must not relax validation.

## 7. Adoption checklist
- Add schema validation for all required report fields.
- Add fixture-based tests for five timeframes x two endpoints, stale/open candles, OHLC anomalies, cross-endpoint disagreement, missing timing fields and provider fallback rejection.
- Integrate this protocol into A-share, US and MAIN CONTROL report producers in separately reviewed changes. Documentation alone is not runtime enforcement.
