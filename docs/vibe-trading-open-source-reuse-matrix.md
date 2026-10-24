# Vibe-Trading V0.8 — open-source reuse matrix

Checked 2026-10-19 against the upstream repositories and package metadata. This
is an engineering selection record, not a claim that any library validates a
market-data source, provider finality, bar closure, or trading permission.

| Project | License / observed release | Fit | Decision |
|---|---|---|---|
| [exchange-calendars](https://github.com/gerrymanoim/exchange_calendars) | Apache-2.0; PyPI 4.13.2 observed | XNYS sessions and exchange calendars; already compatible with the repository's pandas-3 guardrail | Keep as the calendar authority |
| [pandas-market-calendars](https://github.com/rsheftel/pandas_market_calendars) | MIT; v5.0.0 observed | Useful calendar API, but duplicates the existing authority | Do not add a second calendar path |
| [yfinance](https://github.com/ranaroussi/yfinance) | Apache-2.0; current upstream metadata observed | Public Yahoo capture/research input; Yahoo data terms and source semantics remain separate from library license | Keep as a capture boundary, never as finality proof |
| [quantstats](https://github.com/ranaroussi/quantstats) | Apache-2.0; v0.0.86 observed | Reports and portfolio analytics | Optional report-side adapter only; current replay metrics stay deterministic and dependency-free |
| [empyrical](https://github.com/quantopian/empyrical) | Apache-2.0; v0.5.5 observed | Risk/return statistics | Do not add: upstream activity and old dependency floor make it a poor runtime dependency |
| [vectorbt](https://github.com/polakowo/vectorbt) | Apache-2.0 plus Commons Clause; v1.1.1 observed | Fast parameter sweeps and portfolio analysis | Research sandbox only; Commons Clause and large dependency surface are incompatible with runtime inclusion |
| [backtesting.py](https://github.com/kernc/backtesting.py) | AGPL-3.0 | Compact event/backtest API | Do not embed; copyleft and a second execution model are unnecessary here |
| [backtrader](https://github.com/mementum/backtrader) | GPL-3.0 | Event-driven backtesting | Do not embed; license and duplicated execution semantics |
| [zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | Apache-2.0; 3.1.1 observed | Full event-driven research stack and calendar integration | Do not add; heavyweight dependency/database model for the current Replay Lab |

## Minimal combination

The current minimum is `exchange-calendars` plus the repository's existing
deterministic Replay Lab. `yfinance` remains an external capture input, not a
runtime replay dependency. `quantstats` and `vectorbt` may be evaluated in an
isolated research environment later, but neither is required to make the
current report reproducible.

## Current boundary

Replay reports now expose an explicit `BUY_AND_HOLD` benchmark beside each
train/holdout section. This benchmark is a comparison baseline only. It does
not upgrade `UNKNOWN` provider finality or bar closure, and it cannot turn a
fixture, a single-trade sample, or an ungoverned parameter search into an OOS
claim.
