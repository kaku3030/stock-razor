# US SIM legacy inventory quarantine

**2026-10-11 • offline-only read-only contract; no orders or broker mutation.**

The operator clarified the four US SIM LONG holdings existed before STOCK RAZOR
and were left untouched. They are **pre-existing paper inventory**, NOT strategy
trades, earned returns, newly executed fills, or a clean zero-position account.

A private user screenshot showed four positions, while a separate Windows
OpenD read-only query returned four LONG holdings, and empty open/history order
query results for the current query scope. Screenshots and current positions
cannot establish historical order execution identity, realized P&L, or independent
fills. An empty order-history query does not contradict legacy holdings.

This pure `legacy_sim_inventory` contract tests identity, SIMULATE/US scope,
session, bounded readback freshness, unique valid instruments, and optional exact
UI-to-broker quantity agreement. Even all matching fields produce
`QUARANTINED`: the existing holdings and earlier P&L cannot enter new strategy
performance metrics, and order admission stays closed.

Do not write account IDs, screenshots, financial figures, order details, or
broker-native account readbacks to this public repository or public CI logs.
No screenshots or account-specific data are embedded in source/tests.

Next: separately prove AWS/Windows account identity, compare broker-source
position generations, reconcile existing holdings/operator acceptance, and
obtain independent fill-source evidence. A clean virtual strategy sub-ledger
must be isolated from these existing holdings. The first broker SIMULATE order
requires separate explicit user approval.

`PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
`SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.
