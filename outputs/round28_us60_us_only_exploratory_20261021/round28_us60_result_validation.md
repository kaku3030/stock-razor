# Round28 US60 result validation

- Scope: 60 U.S. symbols only, 300 hashed local QFQ/RTH files, D1/1H/15m/5m/1m. This does not complete the 70 U.S. + 30 A-share cohort.
- Quality quarantine: 467 invalid OHLCV rows across 23 symbols and 420 affected symbol-session pairs; entire affected sessions removed across periods and timeframes. Raw captures were not modified.
- Round24 six-arm accounting: maximum equity identity residual 1.46e-11; cash nonnegative=True; drawdown nonnegative=True.
- S2 candidate ledger reconciliation: transaction counts and net P&L agree with all nine candidate metric rows (three windows × three costs) within $0.05.
- S2 candidate equity curve audit: 2,283,930 rows across 5/10/20 bps; maximum equity identity residual 3.73e-11; minimum drawdown 0.
- Compressed curve: s2_candidate_equity_curve.csv.gz (10,252,228 bytes). SHA-256 of the uncompressed CSV: 20348514bec3748883a83d3246798f4460f5b8f0e3cc3d87f221e0ae8cf0ff7f.
- Validation run: tests/test_validate_research_universe_capture.py, 8 passed; Python compile and JSON/diff checks are run before commit.
- Strategy gate: this is exploratory only. Official frozen S2 rules, point-in-time membership, provider finality, timestamp semantics, and independent data-quality signoff are unresolved. No strategy promotion or trading is permitted.
