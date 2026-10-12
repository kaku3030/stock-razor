# TickFlow Premium Secret: IAM-owner least-privilege authorization

Status: **CORRECT SECRET READ VERIFIED; NO IAM CHANGE REQUESTED.**
This is a historical access investigation and a conditional contingency
runbook, not authorization or a reason to change AWS production permissions.
The 2026-10-12 AWS SSM read-only boto3 probe verified
`GetSecretValue` **PASS** for
`stock-razor/tickflow/premium-api-key` under EC2 role
`StockRazorEc2SsmInstanceRole`. A VersionId was returned; no SecretString
was printed, stored or disclosed, and no IAM policy was changed. This does
**not** establish separate `DescribeSecret` or actual TickFlow WS access.
**Do not apply the historical IAM policy unless a NEW denial is observed
against this exact correct Secret and independently approved.**

## Exact evidence and boundaries

On 2026-10-12, an authorized, isolated, read-only GitHub Actions run
[#38224440627](https://github.com/kaku3030/stock-razor/actions/runs/38224440627)
at `main=ab103a6ae6cc9a44d024af33a6ca3137c23a77fe` produced
only sanitized fixed-enum classification:

- `OIDC`, `SSM`, ephemeral `AWS CLI`: PASS;
- remote execution identity: `StockRazorEc2SsmInstanceRole`;
- `TICKFLOW_SECRET_AUDIT_DESCRIBE_DENY_CAUSE=IDENTITY_NO_ALLOW`;
- `TICKFLOW_SECRET_AUDIT_GET_SECRET_DENY_CAUSE=IDENTITY_NO_ALLOW`;
- `KMS=NOT_VERIFIED`; `TickFlow WebSocket=NOT_REACHED`.

**Historical scope only:** The audit above checked
`stock-razor/tickflow/premium`, **NOT** the correct Secret
`stock-razor/tickflow/premium-api-key`. It proves a denied operation for
the *old name*, not a missing Allow for the confirmed real Secret.
The later exact-name EC2 `GetSecretValue` read is **PASS**. Do not use
the old `IDENTITY_NO_ALLOW` to infer that the current EC2 role needs
an added policy or KMS permission.

## Conditional private operator preflight (ONLY after a new confirmed denial)

1. Privately verify the existing Premium Secret under **AWS Secrets Manager,
   Tokyo `ap-northeast-1`**. The approved canonical name is
   `stock-razor/tickflow/premium-api-key`. Verify that this existing Secret is the
   intended source; inspect **metadata only** to obtain its real full ARN.
   Never create a second Secret to work around a denied read.
2. In **AWS IAM → Roles**, open **`StockRazorEc2SsmInstanceRole`** and
   inspect attached and inline policies and permissions boundaries without
   publishing the policy document in this **public** GitHub repository.
3. Check whether the EC2 instance profile really uses that role; identity
   was verified by IMDS and SSM in the run above. Verify any existing Allow
   resource scope, exact ARN suffix, conditions and relevant SCP/RCP before
   changing it. Do not broaden GitHub's separate OIDC/Ops role.
4. Obtain an **explicit, separate operator approval** for a change to the
   EC2 role policy; this document and the user's permission to run read-only
   engineering are **not** approval for IAM modifications.

## Contingency policy scope (historical template — do NOT apply now)

Replace `<CONFIRMED_EXACT_SECRET_ARN>` **privately** with the verified full
Secret ARN, *not* the plain Secret name:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadOnlyApprovedTickFlowPremiumSecret",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "<CONFIRMED_EXACT_SECRET_ARN>"
    }
  ]
}
```

**Do not attach this policy based on the current evidence: exact Secret
`GetSecretValue` has already passed.** If a separate approved incident
later requires an IAM change, attach a reviewed narrowly scoped statement
**only to the EC2 role** named above.
Do not use `"Resource": "*"`, `"secretsmanager:*"`, an unrelated
`iam:*` grant, or an unrestricted ARN suffix. If the Secret uses a
customer-managed KMS key, confirm its full key ARN and actual failure
evidence before separately considering a scoped `kms:Decrypt`. Never
assume a KMS grant is necessary merely because Secrets Manager fails.

For normal application reads, `GetResourcePolicy`, `ListSecrets`,
`iam:*`, AWS console read permissions, and GitHub Ops role access to the
key are **not required**. Lack of diagnostic `GetResourcePolicy` should
not be misconstrued as failure after the two essential Secret calls pass.

## Conditional regression acceptance and rollback (no present change)

1. If investigating a **new** exact-Secret denial, re-run **one**
   approved read-only workflow from protected `main`:
   `audit-tickflow-secret-access.yml`, fixed secret_ref
   `stock-razor/tickflow/premium-api-key`. Check the GitHub run's source SHA.
2. Expected sanitized evidence:
   `CALLER_ROLE=StockRazorEc2SsmInstanceRole`,
   `METADATA=FOUND`, `GET_SECRET=AUTHORIZED_NO_VALUE_EMITTED`,
   `SECRETSTRING=NOT_EMITTED`, `MUTATIONS=NONE`. Secret contents and
   error details must never enter GitHub public logs.
3. If `DescribeSecret` or `GetSecretValue` is denied, classify and stop.
   If the error now indicates KMS or a custom key, resolve that separately
   with actual metadata; do not blindly add permissions.
4. **Only after Secret read passes**, conduct a separately authorized
   **bounded TickFlow Premium WebSocket** probe during an active A-share
   session. Confirm server `subscribed` ACK, initial cached snapshots,
   subsequent provider timestamp progression, and independent freshness,
   closure and reliability. Do not equate ACK or an initial cached quote
   with streaming qualification.
5. Record the change ticket/approver, policy name, private resource
   inventory reference, read-only workflow run ID, and rollback action in
   an access-controlled venue. To roll back, remove only the new statement
   or restore the previous policy version, then validate previous scope.

**Always blocked until fully qualified:**
`PAPER_AUTO_READY=NO`,
`RADAR_ADMISSION=BLOCKED`,
`SOURCE_ARBITER_ADMISSION=BLOCKED`,
`LIVE_TRADE=NO`.

AWS reference: [identity-based secret permissions](https://docs.aws.amazon.com/secretsmanager/latest/userguide/auth-and-access_iam-policies.html)
and [AccessDenied error semantics](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_access-denied.html).
