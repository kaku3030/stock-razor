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

if [[ "$#" -ne 7 ]]; then
  echo 'TICKFLOW_PREMIUM_SETUP=INVALID_ARGUMENTS'
  exit 2
fi

revision="$1"
secret_arn="$2"
probe_hash="$3"
requirements_hash="$4"
bootstrap_hash="$5"
ws_seconds="$6"
quote_only="$7"
[[ "$ws_seconds" =~ ^(0|10|15|30|60)$ ]]
[[ "$quote_only" == true || "$quote_only" == false ]]
if [[ "$quote_only" == true ]]; then
  [[ "$ws_seconds" == 0 ]]
fi
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
  find "$stage/awscli-installer" -type f -name aws -exec chmod u+x {} + 2>/dev/null || true
  probe_stage=RUN_AWS_CLI_INSTALLER
  "$stage/awscli-installer/aws/install" \
    -i "$stage/aws-cli" -b "$stage/bin" >/dev/null 2>&1
  probe_stage=VERIFY_AWS_CLI_INSTALL
  aws_cli="$stage/aws-cli/v2/current/bin/aws"
  [[ -x "$aws_cli" ]] || aws_cli="$stage/bin/aws"
  if [[ ! -x "$aws_cli" ]]; then
    aws_cli="$(find "$stage/aws-cli" -type f -name aws -perm -u+x -print -quit 2>/dev/null || true)"
  fi
  [[ -x "$aws_cli" ]] || aws_cli="$stage/awscli-installer/aws/dist/aws"
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
caller_arn="$("$aws_cli" sts get-caller-identity --query Arn --output text 2>/dev/null || true)"
if [ -n "$caller_arn" ]; then
  printf 'TICKFLOW_PREMIUM_CALLER_ARN=%s\n' "$caller_arn"
else
  printf 'TICKFLOW_PREMIUM_CALLER_ARN=UNKNOWN\n'
fi
probe_stage=READ_SECRET
# Capture only the CLI error stream to a private temporary file; it is never
# emitted into Actions logs, and the EXIT trap deletes it on every path.
if secret_json="$("$aws_cli" secretsmanager get-secret-value --region ap-northeast-1 --secret-id "$secret_arn" --query SecretString --output text 2>"$stage/secret-read-error")"; then
  :
else
  secret_error_class=UNKNOWN
  if grep -Eq 'An error occurred \((AccessDeniedException|AccessDenied)\)' "$stage/secret-read-error"; then
    secret_error_class=ACCESS_DENIED
  elif grep -Eq 'An error occurred \(ResourceNotFoundException\)' "$stage/secret-read-error"; then
    secret_error_class=RESOURCE_NOT_FOUND
  elif grep -Eq 'An error occurred \(DecryptionFailure\)' "$stage/secret-read-error"; then
    secret_error_class=DECRYPTION_FAILURE
  elif grep -Eq 'An error occurred \(InvalidRequestException\)' "$stage/secret-read-error"; then
    secret_error_class=INVALID_REQUEST
  elif grep -Eq 'An error occurred \(InvalidParameterException\)' "$stage/secret-read-error"; then
    secret_error_class=INVALID_PARAMETER
  elif grep -Eq 'An error occurred \((InvalidClientTokenId|UnrecognizedClientException)\)' "$stage/secret-read-error"; then
    secret_error_class=INVALID_CLIENT_TOKEN
  elif grep -Eq 'An error occurred \(ExpiredToken(Exception)?\)' "$stage/secret-read-error"; then
    secret_error_class=EXPIRED_TOKEN
  elif grep -Eq 'An error occurred \((ThrottlingException|TooManyRequestsException)\)' "$stage/secret-read-error"; then
    secret_error_class=THROTTLED
  elif grep -Eiq 'Could not connect to the endpoint URL|Connect timeout|Read timeout|SSL validation failed' "$stage/secret-read-error"; then
    secret_error_class=ENDPOINT_UNREACHABLE
  elif grep -Eiq 'Unable to locate credentials|Partial credentials found' "$stage/secret-read-error"; then
    secret_error_class=CREDENTIALS_MISSING
  fi
  printf 'TICKFLOW_PREMIUM_SECRET_ERROR_CLASS=%s\n' "$secret_error_class"
  exit 254
fi
probe_stage=PARSE_SECRET
export TICKFLOW_API_KEY="$(printf '%s' "$secret_json" | "$venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("api_key") if isinstance(d,dict) and set(d)=={"api_key"} else None; assert isinstance(v,str) and v.strip(); print(v,end="")')"
[[ -n "$TICKFLOW_API_KEY" ]]
unset secret_json

probe_stage=RUN_PREMIUM_PROBE
# One-quote mode: one REST request, no K-line, depth or WebSocket.
# Keep the old broad smoke accessible only by explicit quote_only=false.
probe_args=(--mode premium --location AWS_TOKYO_SSM_ISOLATE
  --symbols 159611.SZ 518880.SH --ws-seconds "$ws_seconds")
if [[ "$quote_only" == true ]]; then
  probe_args+=(--quote-only)
fi
result="$("$venv/bin/python" "$stage/probe.py" "${probe_args[@]}" 2>/dev/null)"
probe_stage=VALIDATE_RESULT
printf '%s\n' "$result" | STOCK_RAZOR_TICKFLOW_PROBE_CACHE_PATH="$root/last-sanitized-probe.json" STOCK_RAZOR_PROBE_REPO_SHA="$revision" TICKFLOW_ONE_QUOTE_SCOPE="$quote_only" python3 -c '
import json, os, sys, tempfile
from datetime import datetime, timezone
d=json.load(sys.stdin)
assert d["mode"] == "premium" and d["api_key_present"] is True
expected_scope=os.environ.get("TICKFLOW_ONE_QUOTE_SCOPE","")
assert d.get("request_scope") == (
    "ONE_REALTIME_QUOTE_BATCH_ONLY" if expected_scope == "true"
    else "STANDARD_ISOLATED_PROBE"
)
if expected_scope == "true":
    ops=d.get("operations",[])
    assert len(ops) <= 2
    assert ops and ops[0] == {"name":"sdk_import","operation":"COMPLETED"}
    assert ops[1].get("name") == "realtime_quote"
assert d["canonical_write"] is False and d["order_execution"] is False
assert d["source_arbiter_admission"] == "BLOCKED" and d["radar_admission"] == "BLOCKED"
assert d["live_trade"] is False and d["can_confirm_signal"] is False
assert isinstance(d["operations"],list) and len(d["operations"]) <= 20
allowed_names={"sdk_import","realtime_quote","kline_1m","kline_5m","kline_15m","kline_30m","kline_60m","five_level_depth","websocket_quote_smoke"}
allowed_states={"COMPLETED","NO_EVENTS_OBSERVED","OBSERVED","CLOSE_FAILED","FAILED","BLOCKED","SKIPPED","ERROR"}
ops=[]
for raw in d["operations"]:
    assert isinstance(raw,dict) and raw.get("name") in allowed_names
    state=raw.get("operation")
    assert state in allowed_states
    item={"name":raw["name"],"operation":state}
    for field in ("elapsed_ms","row_count"):
        value=raw.get(field)
        if type(value) in (int,float) and 0 <= value <= 1e8:
            item[field]=value
    if type(raw.get("schema_qualified")) is bool:
        item["schema_qualified"]=raw["schema_qualified"]
    summary=raw.get("summary") or {}
    if isinstance(summary,dict):
        for field in ("freshness","closure"):
            if summary.get(field) in ("NOT_VERIFIED","PROVEN","UNPROVEN","PASS","BLOCKED"):
                item[field]=summary[field]
    if raw["name"] == "websocket_quote_smoke":
        # Only finite bounded counters from provider callbacks, never
        # symbols, quote payload, raw error text or unqualified latency.
        for field in (
            "quote_callbacks", "quote_events", "unique_quote_samples",
            "initial_snapshot_candidates", "post_initial_update_candidates",
            "duplicate_timestamp_events", "out_of_order_timestamp_events",
            "unrequested_symbol_events", "invalid_timestamp_events",
            "error_callbacks",
        ):
            value=raw.get(field)
            if type(value) is int and 0 <= value <= 1000000:
                item[field]=value
        for field in ("connection_call","subscription_call"):
            value=raw.get(field)
            if value in ("PASS","FAIL","NOT_VERIFIED"):
                item[field]=value
        state=raw.get("background_thread_state")
        if state in ("ALIVE","STOPPED","UNOBSERVABLE"):
            item["background_thread_state"]=state
        item["background_thread_not_provider_connection_proof"]=True
        item["subscription_ack_evidence"]="NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK"
        item["sample_latency_qualification"]="NOT_VERIFIED"
        item["post_initial_candidates_not_confirmed_live"]=True
    ops.append(item)
safe={
    "schema":"stock_razor_tickflow_sanitized_probe_v0_1",
    "mode":"premium",
    "request_scope":d["request_scope"],
    "observed_at_utc":datetime.now(timezone.utc).isoformat(),
    "repo_sha":os.environ["STOCK_RAZOR_PROBE_REPO_SHA"],
    "operations":ops,
    "data_qualification":"NOT_VERIFIED",
    "radar_admission":"BLOCKED",
    "source_arbiter_admission":"BLOCKED",
    "live_trade":False,
}
dest=os.environ["STOCK_RAZOR_TICKFLOW_PROBE_CACHE_PATH"]
directory=os.path.dirname(dest)
os.makedirs(directory,mode=0o755,exist_ok=True)
with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=directory,delete=False) as handle:
    tmp=handle.name
    json.dump(safe,handle,sort_keys=True,separators=(",",":"))
    handle.flush()
    os.fsync(handle.fileno())
try:
    os.chmod(tmp,0o644)
    os.replace(tmp,dest)
except BaseException:
    try: os.unlink(tmp)
    except OSError: pass
    raise
print(json.dumps(safe,sort_keys=True))
'
probe_stage=COMPLETE
echo 'TICKFLOW_PREMIUM_PROBE_EXECUTED=YES'
echo 'TICKFLOW_CLOUD_DATA_ADMISSION=BLOCKED'
echo 'RADAR_ADMISSION=BLOCKED'
echo 'LIVE_TRADE=NO'
