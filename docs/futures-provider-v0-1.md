# Futures Provider Lane V0.1

## Audit result

The canonical baseline is merge commit `cc0cca3afc17bd5661bff4fd90026d7afd54df53`.
The repository had no futures adapter or futures contract mapping at that
baseline. The existing OpenD binding remains US-equity scoped; an earlier GC
permission failure is not treated as entitlement evidence.

The FREE-FIRST candidate is Yahoo Finance through the already-declared
`yfinance` dependency:

| Root | Exchange | Candidate symbol | V0.1 status |
|---|---|---|---|
| GC | COMEX | `GC=F` | delayed/vendor-continuous candidate |
| CL | NYMEX | `CL=F` | delayed/vendor-continuous candidate |
| SI | COMEX | `SI=F` | delayed/vendor-continuous candidate |
| HG | COMEX | `HG=F` | delayed/vendor-continuous candidate |

Yahoo documents intervals including `1m`, `5m`, `15m`, `1h`, and `1d`, with
intraday history limited to recent retention. V0.1 therefore accepts
`1m/5m/15m/1h/1d` at the adapter boundary but does not claim that every
instrument is available at every interval. A returned row is evidence only;
`delivery_mode` and entitlement remain `UNKNOWN`.

AKShare's documented futures minute/spot interfaces are domestic futures
interfaces and do not establish COMEX/NYMEX coverage for these four roots.
They are not silently used as a fallback.

## Contract semantics

`vendor_continuous` is a separate stream feed from `actual_contract`.
`GC=F`, `CL=F`, `SI=F`, and `HG=F` are never treated as research truth for an
actual contract month. An actual-contract row must carry an explicit
`contract_symbol`; a continuous mapping must carry the session date, source,
and evidence. Missing fields fail closed.

The STOCK RAZOR roll rule is deliberately conservative: at a completed
session boundary, exchange contract metadata must be verified and the next
contract must lead both volume and open interest for two consecutive sessions.
Otherwise the mapping remains unchanged. V0.1 does not price-stitch,
back-adjust, or infer a roll from a vendor continuous ticker.

## Runtime boundary

The provider is read-only and produces canonical `ProviderEvent` values for
the existing LiveFeed ingress. It does not open an order connection, subscribe
to a live feed, promote freshness to REALTIME, or alter Radar/Main Control
qualification.

## Currentness and qualification boundary

`data_provider/futures_qualification.py` is the small futures-specific gate
before the existing two-phase LiveFeed qualification harness. It requires an
independently verified exchange holiday calendar, an active session (including
the daily break and weekend closure), a timezone-aware non-future timestamp,
bounded age, positive progress evidence, volume, and unambiguous contract/feed
metadata. Duplicate or non-progress events remain subject to the existing
strict continuity comparator; disconnects and generation rollover clear prior
trust. `UNKNOWN` or `DELAYED` delivery remains blocked, so Yahoo timestamps
never establish REALTIME or LIVE.

The session policy is intentionally conservative: an unverified holiday
calendar is not treated as proof of currentness, and ambiguous roll state or
missing actual-contract metadata fails closed. This is evidence qualification,
not entitlement proof or production controller LIVE authority.

External references used for this audit:

- [Yahoo Finance commodity futures](https://finance.yahoo.com/markets/commodities/)
- [yfinance download intervals and retention](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
- [AKShare futures interfaces](https://github.com/akfamily/akshare/blob/main/docs/data/futures/futures.md)
