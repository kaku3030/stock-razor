# US OpenD watch-ownership / aggregate quota review V0.1

This is a **pure offline research review**, not full-market discovery, a scheduler, a live subscription manager or an execution pathway. It consumes an existing AI Monitor `WatchUniverseSnapshot` and independently supplied OpenD audit aggregates.

- Priority is **portfolio holdings > user pins > Radar-promoted watch candidates**. Multiple ownership sources are preserved by the existing Active Watch Universe; the review only ranks active US watches that are not in the supplied subscribed-symbol list.
- Requires a fresh (<=120 s) watch snapshot, verified aggregate `total_used` + `remain` values **with an independently observed timezone-aware quota timestamp no older than 120 seconds**, bounded symbols, and a bounded candidate list. Invalid or unknown inputs fail closed.
- Returns only `candidates_for_review` with `MANUAL_QUOTA_AND_ENTITLEMENT_REVIEW_REQUIRED`. **No subscribe/unsubscribe calls or runnable instructions**.
- The OpenD aggregate quota audit is not a per-subtype entitlement proof. `QUOTE`, `K_1M`, `K_15M`, `K_60M` permissions and concurrent connection ownership can differ; a nonzero aggregate remaining count is not an authorization to add symbols.
- This review **does not find market-wide opportunities**. Full-market opportunity discovery requires a separate legal universe and a scalable coarse screening data source; OpenD detailed subscriptions should be allocated only after independent discovery, eligibility and freshness gates.
- `execution_permission=BLOCKED`, `radar_admission=BLOCKED`, `source_arbiter_admission=BLOCKED`, `live_trade=false` always.

Next engineering phases: independently verify per-subtype OpenD entitlements and active-connection quota, add reproducible coarse-screen candidate evidence and staleness checks, simulate subscription churn/rate-limits without provider calls, and only then design a guarded executor in a separate reviewed PR. No AWS deploy, paid provider call or trading in this PR.
