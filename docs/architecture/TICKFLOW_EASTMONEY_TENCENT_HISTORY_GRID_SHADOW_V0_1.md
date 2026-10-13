# Eastmoney / Tencent Historical Grid Witness V0.1

This revision adds independent historical-only research evidence to the existing AWS TickFlow acceptance audit. It does not add provider requests; the Tencent historical Kline is already fetched and independently qualified. The extra witness compares privately cached Eastmoney labels and OHLC against the qualified Tencent historical bars.

Fixed two ETFs, 15m/60m. The comparator requires original Eastmoney provider labels, trusted source lineage, fresh schema cache, no adjustment, three shared complete previous Shanghai sessions, exact end-of-bar grid agreement, valid OHLC, and at least 90% of latest three shared-session bars within one ETF quote tick (0.001 CNY) across all four OHLC fields. The output is a finite enum without dates, prices, payloads or secrets.

It never changes the Eastmoney observer's UNKNOWN production timestamp semantics, never repairs TickFlow OHLC, never certifies real-time finality or continuity, and never removes existing source arbitration, Radar, paper or live-trading blocks. The old independent unqualified reference comparison remains separate. Roll back by reverting this audit-only change.
