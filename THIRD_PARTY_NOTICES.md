# Third-Party Notices

This repository includes software derived from third-party projects. The
following notice applies to the files identified below.

## AlphaSift

- Project: AlphaSift
- Source: https://github.com/ZhuLinsen/alphasift
- Referenced revision: `9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf`
- License: Apache License 2.0
- Included and modified files: `src/services/screening/**/*.py` and
  `src/services/screening/strategies/*.yaml`
- License copy: `src/services/screening/LICENSE`

The included code has been modified and integrated into
`daily_stock_analysis`. Per-file headers identify the source revision and
modification status.

## GetData AAPL 12h OHLCV sample

- Project: `getdata-finance/aapl-12h-ohlcv-stocks-historical-data`
- Source: https://github.com/getdata-finance/aapl-12h-ohlcv-stocks-historical-data
- Referenced revision: `e9cebf45a7b68ca87e537c1f2d7f7ea312e79a1b`
- Referenced source blob: `AAPL_12h.csv` at
  `a1d9e2cbced456e2a15f091a389f7382e4f236ec`
- License: MIT
- Included data slice: source rows 2-9, normalized into
  `tests/fixtures/strategy_lab/aapl_getdata_12h_recorded_fixture_v1.json`
- License copy: `tests/fixtures/strategy_lab/LICENSE.getdata-finance.txt`

The fixture is used only for deterministic historical-replay and
point-in-time source-authority tests. It does not grant or imply live market
data rights, provider Currentness semantics, routing authority, or trading
authority.
