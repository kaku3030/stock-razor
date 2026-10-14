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

The loop never merges PRs, changes secrets/IAM, deploys production, enables Radar/Paper,
or executes trades. The workflow remains manual-only and requires an explicit
dispatch confirmation. Resuming a prior state is explicit and uses the same queue;
a changed queue or malformed state is rejected.

The existing DeepSeek+Aider workflow remains a separate controlled E2E lane. Its
generation job is untrusted, its patch is checked in a secretless job, and publication
is PR-only. This 120-minute loop does not silently enable that workflow or claim that
a DeepSeek API call succeeded.
