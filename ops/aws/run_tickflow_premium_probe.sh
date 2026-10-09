#!/usr/bin/env bash
set -euo pipefail
umask 077

# Stage-only diagnostics: no secret, command arguments, URLs, or provider payloads.
probe_stage=INIT

cleanup() {
  local rc=$?
  trap - EXIT
  unset TICKFLOW_API_KEY secret_json
  if [[ -n ${stage:-} ]]; then
    rm -rf -- "$stage"
  fi
  if (( rc != 0 )); then
    printf 'TICKFLOW_PREMIUM_FAILED_STAGE=%s\n' "$probe_stage"
    printf 'TICKFLOW_PREMIUM_AWS_CLI_STAGE=%s\n' "$probe_stage"
    printf 'TICKFLOW_PREMIUM_EXIT_CLASS=NONZERO\n'
  fi
  exit "$rc"
}

trap cleanup EXIT

if [[ "$#" -ne 5 ]]; then
  echo 'TICKFLOW_PREMIUM_SETUP=INVALID_ARGUMENTS'
  exit 2
fi

revision="$1"
secret_arn="$2"
probe_hash="$3"
requirements_hash="$4"
bootstrap_hash="$5"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
[[ "$probe_hash" =~ ^[0-9a-f]{64}$ ]]
[[ "$requirements_hash" =~ ^[0-9a-f]{64}$ ]]
[[ "$bootstrap_hash" =~ ^[0-9a-f]{64}$ ]]
[[ "${TICKFLOW_PREMIUM_PROBE_ENABLED:-false}" == true ]]
[[ "${TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED:-false}" == true ]]
[[ "$secret_arn" =~ ^arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:stock-razor/tickflow/premium-[A-Za-z0-9+=,.@_-]{6,}$ ]]

unset TICKFLOW_PREMIUM_PROBE_ENABLED TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 PIP_CONFIG_FILE=/dev/null
export PIP_INDEX_URL=https://pypi.org/simple PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1

root=/opt/stock-razor-tickflow-premium-probe
stage="$(mktemp -d -t sr-tickflow-premium.XXXXXXXX)"
base="https://raw.githubusercontent.com/kaku3030/stock-razor/$revision"
probe_stage=DOWNLOAD_BOOTSTRAP
curl --fail --silent --show-error --max-time 20 "$base/ops/aws/run_tickflow_premium_probe.sh" -o "$stage/bootstrap.sh" 2>/dev/null
printf '%s  %s\n' "$bootstrap_hash" "$stage/bootstrap.sh" | sha256sum -c - >/dev/null
curl --fail --silent --show-error --max-time 20 "$base/scripts/probe_tickflow_isolated.py" -o "$stage/probe.py" 2>/dev/null
curl --fail --silent --show-error --max-time 20 "$base/ops/requirements/tickflow-isolated-v0.1.txt" -o "$stage/requirements.txt" 2>/dev/null
printf '%s  %s\n' "$probe_hash" "$stage/probe.py" | sha256sum -c - >/dev/null
printf '%s  %s\n' "$requirements_hash" "$stage/requirements.txt" | sha256sum -c - >/dev/null

probe_stage=VERIFY_ARTIFACTS
mkdir -p "$root"
venv="$root/venv"
[[ -x "$venv/bin/python" ]] || python3 -m venv "$venv" >/dev/null 2>&1
probe_stage=INSTALL_DEPENDENCIES
"$venv/bin/python" -m pip install --disable-pip-version-check --no-input --quiet -r "$stage/requirements.txt" >/dev/null 2>&1

# The key is returned only into this process environment; never echo it, pass
# it as an argument, write it to disk, or include it in a report.
probe_stage=READ_SECRET
aws_cli="$(command -v aws 2>/dev/null || true)"
if [[ -z "$aws_cli" ]]; then
  for candidate in "$root/bin/aws" /usr/local/bin/aws /usr/bin/aws /snap/bin/aws /usr/local/aws-cli/v2/current/bin/aws /opt/aws-cli/v2/current/bin/aws; do
    if [[ -x "$candidate" ]]; then
      aws_cli="$candidate"
      break
    fi
  done
fi
if [[ -z "$aws_cli" ]]; then
  probe_stage=INSTALL_AWS_CLI
  aws_arch="$(uname -m 2>/dev/null || true)"
  case "$aws_arch" in
    x86_64|amd64) aws_package_arch=x86_64 ;;
    aarch64|arm64) aws_package_arch=aarch64 ;;
    *) printf 'TICKFLOW_PREMIUM_AWS_CLI_ARCH=UNSUPPORTED\n'; exit 126 ;;
  esac
  printf 'TICKFLOW_PREMIUM_AWS_CLI_ARCH=%s\n' "$aws_package_arch"
  probe_stage=DOWNLOAD_AWS_CLI
  mkdir -p "$stage/aws-cli" "$stage/bin"
  curl --fail --silent --show-error --max-time 60 \
    "https://awscli.amazonaws.com/awscli-exe-linux-${aws_package_arch}.zip" \
    -o "$stage/awscliv2.zip" 2>/dev/null
  probe_stage=EXTRACT_AWS_CLI
  python3 -m zipfile -e "$stage/awscliv2.zip" "$stage/awscli-installer" >/dev/null 2>&1
  chmod 0755 "$stage/awscli-installer/aws/install"
  probe_stage=RUN_AWS_CLI_INSTALLER
  "$stage/awscli-installer/aws/install" \
    -i "$stage/aws-cli" -b "$stage/bin" >/dev/null 2>&1
  probe_stage=VERIFY_AWS_CLI_INSTALL
  aws_cli="$stage/aws-cli/v2/current/bin/aws"
  [[ -x "$aws_cli" ]] || aws_cli="$stage/bin/aws"
fi
if [[ ! -x "$aws_cli" ]]; then
  printf 'TICKFLOW_PREMIUM_AWS_CLI=UNAVAILABLE\n'
  exit 127
fi
aws_version_raw="$("$aws_cli" --version 2>&1 || true)"
aws_version="$(printf '%s\n' "$aws_version_raw" | sed -n 's/^aws-cli\/\([^ ]*\).*/\1/p')"
unset aws_version_raw
if [[ -z "$aws_version" ]]; then
  printf 'TICKFLOW_PREMIUM_AWS_CLI=INVALID\n'
  exit 127
fi
printf 'TICKFLOW_PREMIUM_AWS_CLI=AVAILABLE\n'
printf 'TICKFLOW_PREMIUM_AWS_CLI_PATH=%s\n' "$aws_cli"
printf 'TICKFLOW_PREMIUM_AWS_CLI_VERSION=%s\n' "$aws_version"
secret_json="$("$aws_cli" secretsmanager get-secret-value --region ap-northeast-1 --secret-id "$secret_arn" --query SecretString --output text 2>/dev/null)"
export TICKFLOW_API_KEY="$(printf '%s' "$secret_json" | "$venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("api_key") if isinstance(d,dict) and set(d)=={"api_key"} else None; assert isinstance(v,str) and v.strip(); print(v,end="")')"
[[ -n "$TICKFLOW_API_KEY" ]]
unset secret_json

probe_stage=RUN_PREMIUM_PROBE
result="$("$venv/bin/python" "$stage/probe.py" --mode premium --location AWS_TOKYO_SSM_ISOLATE 2>/dev/null)"
probe_stage=VALIDATE_RESULT
printf '%s\n' "$result" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d["mode"] == "premium" and d["api_key_present"] is True
assert d["canonical_write"] is False and d["order_execution"] is False
assert d["source_arbiter_admission"] == "BLOCKED" and d["radar_admission"] == "BLOCKED"
assert d["live_trade"] is False and d["can_confirm_signal"] is False
print(json.dumps({"schema":d["schema"],"mode":d["mode"],"operations":d["operations"],"data_qualification":d["data_qualification"],"radar_admission":"BLOCKED","live_trade":False},sort_keys=True))
'
probe_stage=COMPLETE
echo 'TICKFLOW_PREMIUM_PROBE_EXECUTED=YES'
echo 'TICKFLOW_CLOUD_DATA_ADMISSION=BLOCKED'
echo 'RADAR_ADMISSION=BLOCKED'
echo 'LIVE_TRADE=NO'
