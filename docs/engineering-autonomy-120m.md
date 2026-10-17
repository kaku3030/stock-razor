# Engineering Autonomy 120-minute loop

This is a one-shot, manually dispatched cloud run. It is not a recurring scheduler
and does not run after the workflow completes.

The loop provides:

- a reviewed task queue with a strict schema and allowlisted task kinds;
- atomic state checkpoints so an interrupted run can resume;
- bounded retries per task;
- a finite cost-unit budget;
- a local stop switch file or AUTONOMY_STOP=true;
- fail-closed BLOCKED and STOPPED terminal states.
- a durable Feedback Hub preflight before checkpoint recovery or task work;
  records may come from `US_WINDOW`, `CN_WINDOW`, `US_RADAR`, or `CN_RADAR`.

The loop never merges PRs, changes secrets/IAM, deploys production, enables Radar/Paper,
or executes trades. The workflow remains manual-only and requires an explicit
dispatch confirmation. Resuming a prior state requires an explicit prior GitHub run ID;
a changed queue fingerprint or malformed state is rejected.

The existing DeepSeek+Aider workflow remains a separate controlled E2E lane. Its
generation job is untrusted, its patch is checked in a secretless job, and publication
is PR-only. This 120-minute loop does not silently enable that workflow or claim that
a DeepSeek API call succeeded.

## Current acceptance boundary

This version is a **test-only cloud orchestration scaffold**, not yet a
continuous DeepSeek engineering agent. The reviewed queue contains only pinned
pytest commands; it may finish in seconds. 120 minutes is a *maximum* runtime,
not a guaranteed duration or a claim of autonomous code generation.

The runner rejects unreviewed commands, binds checkpoints to a SHA-256
fingerprint of the exact reviewed queue, charges a conservative synthetic
cost unit **for every attempt**, and applies the remaining wall-clock
deadline to subprocesses. Cost units are **not** DeepSeek billing estimates.

No checkpoint is restored implicitly. To resume, manually dispatch the
workflow with the exact `resume_run_id` from a previous run. A missing cache
or changed queue stops the run. A new run with no ID starts fresh.

ENGINEERING_AUTONOMY_STOP must be set explicitly to `false` for each
authorized manual dispatch; it is fail-closed when absent or `true`.
The variable is sampled when a job starts, **not live** during execution.
To stop a running job immediately, cancel it from GitHub Actions; local
AUTONOMY_STOP is checked only between commands. There is no schedule.

`FEEDBACK_HUB_PATH` must point to persistent cloud storage. The workflow fails
closed when it is absent or corrupt; it never treats a temporary runner-local
database as durable. Feedback records are deduplicated, atomically leased, and
written back with bounded evidence and audit events. This is cloud-side and
does not depend on a Windows computer.

Before enabling multi-hour AI coding, separately prove DeepSeek+Aider E2E
from a fresh code revision with an independent PR, real API cost metering,
and controlled multi-cycle recovery. This scaffold does not achieve that.
