# TickFlow AWS Premium credential ingress V0.1

Status: code-only, default-disabled, not authorized for execution.

The existing isolated workflow remains the only default path. This separate
workflow is dormant unless a human explicitly enables it and supplies a
Tokyo-region Secrets Manager ARN. The API key is never a workflow input,
command argument, repository value, file, log, or report field. It is read
only in the remote process environment, then removed on exit.

The proposed minimum external policy is **not verified or applied by this PR**:

- GitHub OIDC role: no `secretsmanager:*` permission; it may only invoke the
  already-authorized bounded SSM operation.
- EC2 instance role: `secretsmanager:GetSecretValue` on one exact secret ARN;
  no `ListSecrets`, `PutSecretValue`, `DeleteSecret`, or wildcard resource.
- If the secret uses a customer KMS key, `kms:Decrypt` is limited to that one
  key and the Secrets Manager encryption context for that one secret.
- No IAM, KMS, secret, entitlement, billing, or provider account change is
  performed here. Any missing permission or malformed secret blocks closed.

Even when enabled, the probe is read-only and reports
`RADAR_ADMISSION=BLOCKED` and `LIVE_TRADE=NO`; successful SDK requests do not
qualify currentness, continuity, bar closure, or source entitlement.
