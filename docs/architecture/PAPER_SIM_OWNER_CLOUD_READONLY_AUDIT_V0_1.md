# Paper US SIM — Owner-only AWS Read-Only Audit V0.1

## Intent

Enable a protected, computer-independent *read-only* US SIM account inspection without ever enabling trading. The existing workflow `.github/workflows/aws-ssm-sim-account-discovery.yml` remains the sole execution implementation; no new AWS identity, target, provider, or credential path is introduced.

The repository Owner can comment this exact line on merged Paper PR **#698**:

```
/stock-razor paper-sim-audit read-only
```

GitHub checks the owner identity, owner association, exact PR number, exact comment body and latest protected `main` SHA **before assuming the existing AWS role**. Only the fixed existing EC2 target and audited SIM read-only workflow are used. `workflow_dispatch` remains available.

## What this does (and does not) qualify

The existing workflow uses OpenD to discover only explicitly `US` + `SIMULATE` + `STOCK_AND_OPTION` + `ACTIVE` rows, requires exactly one account, and runs bounded non-mutating account/balance/positions/orders/history reads against that explicit SIM account ID, retained only in private process memory. No REAL account readback, trading unlock, provider subscription, order, cancel, or service restart is permitted. Account IDs, private balances, order values, raw provider output and credentials must not appear in GitHub logs.

`SIM_READBACK=PASS_PAPER_BLOCKED` (if achieved) proves only the narrowly scoped SIM readback. Native SIM fills remain `UNSUPPORTED_BY_OPEND`; independent trade receipts, full reconciliation, startup/restart recovery, and cloud Paper execution are still `NOT_VERIFIED/BLOCKED`. The workflow cannot set `PAPER_AUTO_READY`, `RADAR_ADMISSION`, `SOURCE_ARBITER_ADMISSION`, `LIVE_TRADE`, or `TRADE_EXECUTION` to a permissive state.

## Evidence and rollback

Check the exact-main GitHub workflow run `AWS SSM SIM Account Discovery` for a fixed, sanitized `SIM_ACCOUNT_DISCOVERY_SUMMARY`; never confuse SSM transport PASS with the SIM readback gate. Revert this workflow/comment-trigger change to restore manual-only dispatch without affecting the existing read-only SIM inspection implementation.
