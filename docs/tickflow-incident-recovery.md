# TickFlow incident recovery

## Verified credential route

The AWS premium probe resolves the existing `stock-razor/tickflow/premium-api-key`
secret in `ap-northeast-1` inside the EC2 process. It never prints the value.
A failed Windows `StockRazor/TickFlow/APIKey` lookup applies only to that Windows
user. It is not evidence that the AWS credential is absent. A denied
`DescribeSecret` does not imply `GetSecretValue` is denied.

## October 19 regression

The exact-main AWS audit run `39215677005` observed advancing publications
44 to 45, but both were blocked at `S1_60M_NORMALIZE` with
`ROW_COUNT_BELOW_MIN`. All readers then rejected the failed cache envelope.
This demonstrates that advancing sequence and a running service do not prove
usable market data. The affected symbol was 159209.SZ, suspended until 10:30
Shanghai that day; a complete remaining session contains three hourly bars.

Minute ingestion and readers now preserve bounded nonempty short samples.
Daily history still requires four rows. Indicator lookback adequacy remains
separate; short data must retain insufficient-history warnings and cannot
grant signal or trading admission. Empty, malformed, duplicate and reordered
data still fail validation. The deployment verifier rejects blocked caches.

Minute audit and missing-batch recovery use `klines.intraday`; daily history
uses `klines.get`. Do not replace a proven live route with the history endpoint.
The five observation symbols, public workflow allowlist, and independently
verified consumer symbol set must agree. Gold is an observation, not a holding.

## Acceptance evidence

1. Offline regression tests exercise short-hourly cache roundtrips, missing
   symbols, actual verifier subprocesses, and credential-scope diagnostics.
2. Protected main CI must pass before cloud code is updated.
3. The existing controlled TickFlow worker deployment uses its rollback path.
4. Run `audit-cn-tickflow-live-research.yml` and inspect the sanitized result,
   not just the GitHub workflow conclusion. Confirm producer revision,
   successful data status, age, consumer readback and all requested frames.
5. Read `TICKFLOW:FULL` through the connected read-only CN market-data tool.
   MCP deployment and producer deployment are separate facts.

Provider successor closure, latest-bar uncertainty, post-close revisions,
data freshness, indicator history and trading admission are separate checks.
The October 13 vendor email says a successor confirms the preceding bar;
it does not promise immutability. Two identical reads do not prove no later
revision. Keep raw provider values private and do not open trading gates.
