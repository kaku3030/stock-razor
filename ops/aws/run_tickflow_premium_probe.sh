#!/usr/bin/env bash
set -euo pipefail
umask 077

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
trap 'unset TICKFLOW_API_KEY; rm -rf "$stage"' EXIT
base="https://raw.githubusercontent.com/kaku3030/stock-razor/$revision"
curl --fail --silent --show-error --max-time 20 "$base/ops/aws/run_tickflow_premium_probe.sh" -o "$stage/bootstrap.sh" 2>/dev/null
printf '%s  %s\n' "$bootstrap_hash" "$stage/bootstrap.sh" | sha256sum -c - >/dev/null
curl --fail --silent --show-error --max-time 20 "$base/scripts/probe_tickflow_isolated.py" -o "$stage/probe.py" 2>/dev/null
curl --fail --silent --show-error --max-time 20 "$base/ops/requirements/tickflow-isolated-v0.1.txt" -o "$stage/requirements.txt" 2>/dev/null
printf '%s  %s\n' "$probe_hash" "$stage/probe.py" | sha256sum -c - >/dev/null
printf '%s  %s\n' "$requirements_hash" "$stage/requirements.txt" | sha256sum -c - >/dev/null

mkdir -p "$root"
venv="$root/venv"
[[ -x "$venv/bin/python" ]] || python3 -m venv "$venv" >/dev/null 2>&1
"$venv/bin/python" -m pip install --disable-pip-version-check --no-input --quiet -r "$stage/requirements.txt" >/dev/null 2>&1

# The key is returned only into this process environment; never echo it, pass
# it as an argument, write it to disk, or include it in a report.
secret_json="$(aws secretsmanager get-secret-value --region ap-northeast-1 --secret-id "$secret_arn" --query SecretString --output text 2>/dev/null)"
export TICKFLOW_API_KEY="$(printf '%s' "$secret_json" | "$venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("api_key") if isinstance(d,dict) and set(d)=={"api_key"} else None; assert isinstance(v,str) and v.strip(); print(v,end="")')"
[[ -n "$TICKFLOW_API_KEY" ]]
unset secret_json

result="$("$venv/bin/python" "$stage/probe.py" --mode premium --location AWS_TOKYO_SSM_ISOLATE 2>/dev/null)"
printf '%s\n' "$result" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d["mode"] == "premium" and d["api_key_present"] is True
assert d["canonical_write"] is False and d["order_execution"] is False
assert d["source_arbiter_admission"] == "BLOCKED" and d["radar_admission"] == "BLOCKED"
assert d["live_trade"] is False and d["can_confirm_signal"] is False
print(json.dumps({"schema":d["schema"],"mode":d["mode"],"operations":d["operations"],"data_qualification":d["data_qualification"],"radar_admission":"BLOCKED","live_trade":False},sort_keys=True))
'
echo 'TICKFLOW_PREMIUM_PROBE_EXECUTED=YES'
echo 'TICKFLOW_CLOUD_DATA_ADMISSION=BLOCKED'
echo 'RADAR_ADMISSION=BLOCKED'
echo 'LIVE_TRADE=NO'
