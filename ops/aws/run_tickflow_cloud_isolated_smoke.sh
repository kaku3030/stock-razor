#!/usr/bin/env bash
# Stock Razor: isolated, bounded AWS TickFlow SDK smoke. Not a provider service.
set -euo pipefail
umask 077

if [[ "$#" -ne 4 ]]; then
  echo 'TICKFLOW_CLOUD_SETUP=INVALID_ARGUMENTS'
  exit 2
fi

revision="$1"
mode="$2"
probe_hash="$3"
requirements_hash="$4"

[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'TICKFLOW_CLOUD_SETUP=INVALID_REVISION'; exit 2; }
[[ "$probe_hash" =~ ^[0-9a-f]{64}$ ]] || { echo 'TICKFLOW_CLOUD_SETUP=INVALID_PROBE_HASH'; exit 2; }
[[ "$requirements_hash" =~ ^[0-9a-f]{64}$ ]] || { echo 'TICKFLOW_CLOUD_SETUP=INVALID_REQUIREMENTS_HASH'; exit 2; }
[[ "$mode" == "metadata" || "$mode" == "free" || "$mode" == "premium-contract" ]] || { echo 'TICKFLOW_CLOUD_SETUP=PREMIUM_REQUIRES_SEPARATE_ENTITLEMENT_GATE'; exit 2; }

# AWS SSM process environment is not a source of paid-data authorization.
# This smoke is *intentionally* unable to use a premium credential.
unset TICKFLOW_API_KEY TICKFLOW_BASE_URL TICKFLOW_FREE_BASE_URL
export PYTHONIOENCODING=utf-8
export PYTHONDONTWRITEBYTECODE=1
export PIP_CONFIG_FILE=/dev/null
export PIP_INDEX_URL=https://pypi.org/simple
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1

root="/opt/stock-razor-tickflow-isolated"
venv="$root/venv"
stage="$(mktemp -d -t sr-tickflow-cloud.XXXXXXXX)"
trap 'rm -rf "$stage"' EXIT

base="https://raw.githubusercontent.com/kaku3030/stock-razor/$revision"
if ! curl --fail --silent --show-error --max-time 20 \
  "$base/scripts/probe_tickflow_isolated.py" -o "$stage/probe.py" 2>/dev/null; then
  echo 'TICKFLOW_CLOUD_SETUP=PROBE_FETCH_FAILED'
  exit 1
fi
if ! curl --fail --silent --show-error --max-time 20 \
  "$base/ops/requirements/tickflow-isolated-v0.1.txt" -o "$stage/requirements.txt" 2>/dev/null; then
  echo 'TICKFLOW_CLOUD_SETUP=REQUIREMENTS_FETCH_FAILED'
  exit 1
fi

# Verify *each* cloud-fetched artifact against the exact GitHub runner checkout.
if ! printf '%s  %s\n' "$probe_hash" "$stage/probe.py" \
   | sha256sum -c - >/dev/null 2>&1; then
  echo 'TICKFLOW_CLOUD_SETUP=PROBE_SHA256_MISMATCH'
  exit 1
fi
if ! printf '%s  %s\n' "$requirements_hash" "$stage/requirements.txt" \
   | sha256sum -c - >/dev/null 2>&1; then
  echo 'TICKFLOW_CLOUD_SETUP=REQUIREMENTS_SHA256_MISMATCH'
  exit 1
fi
echo 'TICKFLOW_CLOUD_SOURCE_INTEGRITY=PASS'

# Venv is disjoint from the live US/CN data fabric, production /opt trees,
# system Python site-packages, jobs and systemd units.
mkdir -p "$root"
if [[ ! -x "$venv/bin/python" ]]; then
  if ! python3 -m venv "$venv" >/dev/null 2>&1; then
    echo 'TICKFLOW_CLOUD_SETUP=VENV_UNAVAILABLE'
    exit 1
  fi
fi
if ! "$venv/bin/python" -m pip install \
  --disable-pip-version-check --no-input --quiet \
  -r "$stage/requirements.txt" >/dev/null 2>&1; then
  echo 'TICKFLOW_CLOUD_SETUP=SDK_INSTALL_FAILED'
  exit 1
fi
if ! "$venv/bin/python" -m pip check >/dev/null 2>&1; then
  echo 'TICKFLOW_CLOUD_SETUP=DEPENDENCY_CHECK_FAILED'
  exit 1
fi
if ! "$venv/bin/python" -c \
  'import importlib.metadata as m; assert m.version("tickflow") == "0.1.25"; from tickflow import TickFlow' \
  >/dev/null 2>&1; then
  echo 'TICKFLOW_CLOUD_SETUP=SDK_IMPORT_FAILED'
  exit 1
fi

echo 'TICKFLOW_CLOUD_SDK_IMPORT=PASS'
echo "TICKFLOW_CLOUD_MODE=$mode"
echo "TICKFLOW_CLOUD_PINNED_REVISION=$revision"

# No raw provider payloads, keys, stdout notices or traceback bodies.
# No WebSocket, retry loop, orders, canonical writes, provider service installs.
result="$("$venv/bin/python" "$stage/probe.py" --mode "$mode" \
  --location AWS_TOKYO_SSM_ISOLATE 2>/dev/null)" || {
  echo 'TICKFLOW_CLOUD_SETUP=PROBE_COMMAND_FAILED'
  exit 1
}
printf '%s\n' "$result" | python3 -c '
import json,sys
data=json.load(sys.stdin)
assert data.get("schema") == "stock_razor_tickflow_isolated_probe_v0_1"
assert data.get("location") == "AWS_TOKYO_SSM_ISOLATE"
assert data.get("mode") in ("metadata", "free", "premium-contract")
assert data.get("api_key_present") is False
assert data.get("canonical_write") is False
assert data.get("order_execution") is False
assert data.get("radar_admission") == "BLOCKED"
assert data.get("source_arbiter_admission") == "BLOCKED"
assert data.get("live_trade") is False
assert data.get("can_confirm_signal") is False
assert data.get("data_qualification") == "NOT_VERIFIED"
ops=data.get("operations",[])
if data.get("mode") == "premium-contract":
  assert ops and ops[0]["name"] == "premium_execution_gate"
  assert data.get("premium_execution") == "BLOCKED"
  assert data.get("premium_contract", {}).get("network_execution") is False
  assert data.get("premium_contract", {}).get("blocked_reasons")
else:
  assert ops and ops[0] == {"name":"sdk_import","operation":"COMPLETED"}
print(json.dumps({
  "schema":data["schema"],
  "location":data["location"],
  "mode":data["mode"],
  "sdk_version":data.get("sdk_version"),
  "operations":ops,
  "premium_execution":data.get("premium_execution"),
  "premium_contract":data.get("premium_contract"),
  "source_arbiter_admission":"BLOCKED",
  "data_qualification":"NOT_VERIFIED",
  "radar_admission":"BLOCKED",
  "cloud_independence":"NOT_VERIFIED",
  "paid_entitlement":"NOT_VERIFIED",
  "real_market_slo":"NOT_VERIFIED",
  "live_trade":False,
  "can_confirm_signal":False
},sort_keys=True))
'
echo 'TICKFLOW_CLOUD_ISOLATED_SMOKE_EXECUTED=YES'
echo 'TICKFLOW_CLOUD_DATA_ADMISSION=BLOCKED'
echo 'LIVE_TRADE=NO'
