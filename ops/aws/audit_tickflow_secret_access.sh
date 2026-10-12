#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 1 ]]; then
  echo 'TICKFLOW_SECRET_AUDIT_SETUP=INVALID_ARGUMENTS'
  exit 2
fi

secret_ref="$1"
if [[ "$secret_ref" != 'stock-razor/tickflow/premium' &&
      ! "$secret_ref" =~ ^arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:stock-razor/tickflow/premium-[A-Za-z0-9+=,.@_-]{6,}$ ]]; then
  echo 'TICKFLOW_SECRET_AUDIT_SETUP=INVALID_REFERENCE'
  exit 2
fi

tmp_dir="$(mktemp -d -t sr-tickflow-secret-audit.XXXXXXXX)"
trap 'rm -rf -- "$tmp_dir"' EXIT

classify_error() {
  local error_file="$1"
  if grep -Eq 'An error occurred \((AccessDeniedException|AccessDenied)\)' "$error_file"; then
    echo ACCESS_DENIED
  elif grep -Eq 'An error occurred \(ResourceNotFoundException\)' "$error_file"; then
    echo RESOURCE_NOT_FOUND
  elif grep -Eq 'An error occurred \(DecryptionFailure\)' "$error_file"; then
    echo DECRYPTION_FAILURE
  elif grep -Eq 'An error occurred \(InvalidRequestException\)' "$error_file"; then
    echo INVALID_REQUEST
  elif grep -Eq 'An error occurred \(InvalidParameterException\)' "$error_file"; then
    echo INVALID_PARAMETER
  elif grep -Eiq 'Unable to locate credentials|Partial credentials found' "$error_file"; then
    echo CREDENTIALS_MISSING
  elif grep -Eiq 'Could not connect to the endpoint URL|Connect timeout|Read timeout|SSL validation failed' "$error_file"; then
    echo ENDPOINT_UNREACHABLE
  else
    echo UNKNOWN
  fi
}

aws_cli="$(command -v aws 2>/dev/null || true)"
if [[ -z "$aws_cli" || ! -x "$aws_cli" ]]; then
  echo 'TICKFLOW_SECRET_AUDIT_AWS_CLI=UNAVAILABLE'
  exit 1
fi
echo 'TICKFLOW_SECRET_AUDIT_AWS_CLI=AVAILABLE'

caller_arn="$($aws_cli sts get-caller-identity --query Arn --output text 2>"$tmp_dir/caller.err" || true)"
caller_role=UNKNOWN
if [[ "$caller_arn" =~ :assumed-role/([^/]+)/ ]]; then
  caller_role="${BASH_REMATCH[1]}"
fi
unset caller_arn
if [[ "$caller_role" == UNKNOWN ]]; then
  echo 'TICKFLOW_SECRET_AUDIT_CALLER_ROLE=UNKNOWN'
else
  echo "TICKFLOW_SECRET_AUDIT_CALLER_ROLE=$caller_role"
fi
unset caller_role

metadata="$($aws_cli secretsmanager describe-secret --region ap-northeast-1 --secret-id "$secret_ref" --query '[Name,ARN,KmsKeyId]' --output text 2>"$tmp_dir/describe.err" || true)"
if [[ -z "$metadata" || "$metadata" == None ]]; then
  echo "TICKFLOW_SECRET_AUDIT_METADATA=$(classify_error "$tmp_dir/describe.err")"
  echo 'TICKFLOW_SECRET_AUDIT_KMS_METADATA=NOT_VERIFIED'
else
  read -r canonical_name canonical_arn kms_key_id <<<"$metadata"
  if [[ "$canonical_name" == 'stock-razor/tickflow/premium' ]]; then
    echo 'TICKFLOW_SECRET_AUDIT_METADATA=FOUND'
    echo 'TICKFLOW_SECRET_AUDIT_NAME_MATCH=YES'
  else
    echo 'TICKFLOW_SECRET_AUDIT_METADATA=FOUND'
    echo 'TICKFLOW_SECRET_AUDIT_NAME_MATCH=NO'
  fi
  if [[ "$secret_ref" == arn:* && "$canonical_arn" == "$secret_ref" ]]; then
    echo 'TICKFLOW_SECRET_AUDIT_ARN_MATCH=YES'
  elif [[ "$secret_ref" == arn:* ]]; then
    echo 'TICKFLOW_SECRET_AUDIT_ARN_MATCH=NO'
  else
    echo 'TICKFLOW_SECRET_AUDIT_ARN_MATCH=NOT_APPLICABLE'
  fi
  if [[ -n "$kms_key_id" && "$kms_key_id" != None ]]; then
    echo 'TICKFLOW_SECRET_AUDIT_KMS_KEY=PRESENT'
    if $aws_cli kms describe-key --region ap-northeast-1 --key-id "$kms_key_id" --query KeyMetadata.KeyState --output text >"$tmp_dir/kms.out" 2>"$tmp_dir/kms.err"; then
      echo 'TICKFLOW_SECRET_AUDIT_KMS_METADATA=AVAILABLE'
    else
      echo "TICKFLOW_SECRET_AUDIT_KMS_METADATA=$(classify_error "$tmp_dir/kms.err")"
    fi
  else
    echo 'TICKFLOW_SECRET_AUDIT_KMS_KEY=ABSENT'
    echo 'TICKFLOW_SECRET_AUDIT_KMS_METADATA=NOT_REQUIRED'
  fi
fi
unset metadata canonical_name canonical_arn kms_key_id

if $aws_cli secretsmanager get-resource-policy --region ap-northeast-1 --secret-id "$secret_ref" --query ResourcePolicy --output text >"$tmp_dir/policy.out" 2>"$tmp_dir/policy.err"; then
  echo 'TICKFLOW_SECRET_AUDIT_RESOURCE_POLICY=AVAILABLE'
else
  echo "TICKFLOW_SECRET_AUDIT_RESOURCE_POLICY=$(classify_error "$tmp_dir/policy.err")"
fi

if $aws_cli secretsmanager get-secret-value --region ap-northeast-1 --secret-id "$secret_ref" --query VersionId --output text >"$tmp_dir/value.out" 2>"$tmp_dir/value.err"; then
  echo 'TICKFLOW_SECRET_AUDIT_GET_SECRET=AUTHORIZED_NO_VALUE_EMITTED'
else
  echo "TICKFLOW_SECRET_AUDIT_GET_SECRET=$(classify_error "$tmp_dir/value.err")"
fi

echo 'TICKFLOW_SECRET_AUDIT_ORGANIZATION_POLICY=NOT_VERIFIED'
echo 'TICKFLOW_SECRET_AUDIT_SECRETSTRING=NOT_EMITTED'
echo 'TICKFLOW_SECRET_AUDIT_MUTATIONS=NONE'
echo 'RADAR_ADMISSION=BLOCKED'
echo 'LIVE_TRADE=NO'
