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

if [[ "$#" -ne 7 && "$#" -ne 9 ]]; then
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
# The two extra SHA256s select only the reviewed direct WS ACK evidence path.
# Legacy seven-argument Premium requests are unchanged.
protocol_only=false
protocol_hash=""
sanitizer_hash=""
if [[ "$#" -eq 9 ]]; then
  protocol_only=true
  protocol_hash="$8"
  sanitizer_hash="$9"
fi
[[ "$ws_seconds" =~ ^(0|10|15|30|60|900|3600|7200|9000|14160|16800)$ ]]
[[ "$quote_only" == true || "$quote_only" == false ]]
if [[ "$quote_only" == true ]]; then
  [[ "$ws_seconds" == 0 ]]
fi
if [[ "$protocol_only" == true ]]; then
  [[ "$quote_only" == false && "$ws_seconds" != 0 ]]
  [[ "$protocol_hash" =~ ^[0-9a-f]{64}$ ]]
  [[ "$sanitizer_hash" =~ ^[0-9a-f]{64}$ ]]
fi
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
[[ "$probe_hash" =~ ^[0-9a-f]{64}$ ]]
[[ "$requirements_hash" =~ ^[0-9a-f]{64}$ ]]
[[ "$bootstrap_hash" =~ ^[0-9a-f]{64}$ ]]
[[ "${TICKFLOW_PREMIUM_PROBE_ENABLED:-false}" == true ]]
[[ "${TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED:-false}" == true ]]
# Allow either the original exact ARN or the single fixed existing secret name.
# IAM still determines whether this EC2 identity may read it.
if [[ "$secret_arn" != 'stock-razor/tickflow/premium-api-key' ]]; then
  [[ "$secret_arn" =~ ^arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:stock-razor/tickflow/premium-api-key-[A-Za-z0-9+=,.@_-]{6,}$ ]]
fi

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
if [[ "$protocol_only" == true ]]; then
  curl --fail --silent --show-error --max-time 20 "$base/scripts/tickflow_ws_protocol_probe.py" -o "$stage/ws_protocol.py" 2>/dev/null
  curl --fail --silent --show-error --max-time 20 "$base/scripts/sanitize_tickflow_ws_protocol_probe.py" -o "$stage/ws_sanitizer.py" 2>/dev/null
  printf '%s  %s\n' "$protocol_hash" "$stage/ws_protocol.py" | sha256sum -c - >/dev/null
  printf '%s  %s\n' "$sanitizer_hash" "$stage/ws_sanitizer.py" | sha256sum -c - >/dev/null
fi

probe_stage=VERIFY_ARTIFACTS
mkdir -p "$root"
venv="$root/venv"
[[ -x "$venv/bin/python" ]] || python3 -m venv "$venv" >/dev/null 2>&1
probe_stage=INSTALL_DEPENDENCIES
"$venv/bin/python" -m pip install --disable-pip-version-check --no-input --quiet -r "$stage/requirements.txt" >/dev/null 2>&1
# Fail before reading a key or issuing REST when the official realtime
# transport extra is unavailable in the isolated AWS venv.
probe_stage=VERIFY_REALTIME_EXTRA
if [[ "$ws_seconds" != "0" ]]; then
  if ! "$venv/bin/python" -c 'import importlib.metadata as m; import websockets; assert m.version("websockets") == "15.0.1"' >/dev/null 2>&1; then
    echo 'TICKFLOW_WS_DEPENDENCY=UNAVAILABLE' >&2
    exit 1
  fi
fi

# The key is returned only into this process environment; never echo it, pass
# it as an argument, write it to disk, or include it in a report.
probe_stage=READ_SECRET
cat > "$stage/aws_secrets_manager_get.py" <<'PY'
#!/usr/bin/env python3
"""Read one existing Secrets Manager value without exposing provider credentials."""

from __future__ import annotations

import sys


def _error_class(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    code = error.get("Code") if isinstance(error, dict) else None
    mapping = {
        "AccessDenied": "ACCESS_DENIED",
        "AccessDeniedException": "ACCESS_DENIED",
        "ResourceNotFoundException": "RESOURCE_NOT_FOUND",
        "DecryptionFailure": "DECRYPTION_FAILURE",
        "InvalidRequestException": "INVALID_REQUEST",
        "InvalidParameterException": "INVALID_PARAMETER",
        "InvalidClientTokenId": "INVALID_CLIENT_TOKEN",
        "UnrecognizedClientException": "INVALID_CLIENT_TOKEN",
        "ExpiredToken": "EXPIRED_TOKEN",
        "ExpiredTokenException": "EXPIRED_TOKEN",
        "ThrottlingException": "THROTTLED",
        "TooManyRequestsException": "THROTTLED",
    }
    if code in mapping:
        return mapping[code]
    if type(exc).__name__ in {
        "EndpointConnectionError", "ConnectTimeoutError",
        "ReadTimeoutError", "SSLError",
    }:
        return "ENDPOINT_UNREACHABLE"
    if type(exc).__name__ in {"NoCredentialsError", "PartialCredentialsError"}:
        return "CREDENTIALS_MISSING"
    if isinstance(exc, ValueError):
        return "SECRET_FORMAT_INVALID"
    return "UNKNOWN"


def main(secret_id: str, *, client_factory=None, stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        if client_factory is None:
            import boto3
            client_factory = boto3.client
        response = client_factory(
            "secretsmanager", region_name="ap-northeast-1"
        ).get_secret_value(SecretId=secret_id)
        secret = response.get("SecretString") if isinstance(response, dict) else None
        if not isinstance(secret, str) or not secret.strip():
            raise ValueError("secret string unavailable")
    except Exception as exc:
        print("TICKFLOW_SECRET_ERROR_CLASS=" + _error_class(exc), file=stderr)
        return 1
    print(secret, end="", file=stdout)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("TICKFLOW_SECRET_ERROR_CLASS=INVALID_ARGUMENT", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
PY

probe_stage=VERIFY_AWS_SDK
if ! "$venv/bin/python" -c 'import boto3, botocore; assert boto3.__version__ == "1.43.114"; assert botocore.__version__ == "1.43.114"' >/dev/null 2>&1; then
  printf 'TICKFLOW_PREMIUM_AWS_SDK=UNAVAILABLE\n'
  exit 1
fi
printf 'TICKFLOW_PREMIUM_AWS_SDK=AVAILABLE\n'
caller_arn="$("$venv/bin/python" -c 'import boto3; print(boto3.client("sts", region_name="ap-northeast-1").get_caller_identity()["Arn"])' 2>/dev/null || true)"
if [ -n "$caller_arn" ]; then
  printf 'TICKFLOW_PREMIUM_CALLER_ARN=%s\n' "$caller_arn"
else
  printf 'TICKFLOW_PREMIUM_CALLER_ARN=UNKNOWN\n'
fi
probe_stage=READ_SECRET
if secret_json="$("$venv/bin/python" "$stage/aws_secrets_manager_get.py" "$secret_arn" 2>"$stage/secret-read-error")"; then
  :
else
  secret_error_class="$(sed -nE 's/^TICKFLOW_SECRET_ERROR_CLASS=(ACCESS_DENIED|RESOURCE_NOT_FOUND|DECRYPTION_FAILURE|INVALID_REQUEST|INVALID_PARAMETER|INVALID_CLIENT_TOKEN|EXPIRED_TOKEN|THROTTLED|ENDPOINT_UNREACHABLE|CREDENTIALS_MISSING|SECRET_FORMAT_INVALID|INVALID_ARGUMENT|UNKNOWN)$/\1/p' "$stage/secret-read-error" | tail -n 1)"
  if [[ -z "$secret_error_class" ]]; then
    secret_error_class=UNKNOWN
  fi
  printf 'TICKFLOW_PREMIUM_SECRET_ERROR_CLASS=%s\n' "$secret_error_class"
  exit 254
fi
probe_stage=PARSE_SECRET
export TICKFLOW_API_KEY="$(printf '%s' "$secret_json" | "$venv/bin/python" -c 'import json,sys; d=json.load(sys.stdin); v=d.get("api_key") if isinstance(d,dict) and set(d)=={"api_key"} else None; assert isinstance(v,str) and v.strip(); print(v,end="")')"
[[ -n "$TICKFLOW_API_KEY" ]]
unset secret_json

if [[ "$protocol_only" == true ]]; then
  # Only one bounded quote-channel WebSocket; ZERO REST/K-line/depth calls.
  # Exit 2 means complete/partial protocol evidence lacking updates, not a
  # transport or market-data qualification. Emit only the validated schema.
  probe_stage=RUN_DIRECT_WS_PROTOCOL
  protocol_rc=0
  ws_symbols="${TICKFLOW_WS_SYMBOLS:-159611.SZ 159209.SZ 600519.SH 000001.SZ 300750.SZ 601318.SH 600036.SH 000858.SZ 601398.SH 600900.SH 601888.SH 600276.SH 000333.SZ 002594.SZ 600030.SH 601857.SH 600028.SH 600809.SH 000651.SZ 601012.SH}"
  read -r -a ws_symbol_args <<< "$ws_symbols"
  (( ${#ws_symbol_args[@]} >= 1 && ${#ws_symbol_args[@]} <= 20 )) || {
    echo 'TICKFLOW_WS_SYMBOLS_INVALID' >&2
    exit 2
  }
  protocol_summary="$(TICKFLOW_WS_PROTOCOL_PROBE_OPT_IN=true TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED=true "$venv/bin/python" "$stage/ws_protocol.py" --execute --symbols "${ws_symbol_args[@]}" --seconds "$ws_seconds" 2>/dev/null)" || protocol_rc=$?
  [[ "$protocol_rc" == 0 || "$protocol_rc" == 2 ]]
  probe_stage=SANITIZE_DIRECT_WS_PROTOCOL
  printf '%s\n' "$protocol_summary" | "$venv/bin/python" "$stage/ws_sanitizer.py" --repo-sha "$revision"
  probe_stage=COMPLETE
  echo "TICKFLOW_WS_ACK_PROBE_EXECUTED=YES"
  echo "TICKFLOW_CLOUD_DATA_ADMISSION=BLOCKED"
  echo "RADAR_ADMISSION=BLOCKED"
  echo "LIVE_TRADE=NO"
  exit 0
fi

probe_stage=RUN_PREMIUM_PROBE
# One-quote mode: one REST request, no K-line, depth or WebSocket.
# Keep the old broad smoke accessible only by explicit quote_only=false.
probe_args=(--mode premium --location AWS_TOKYO_SSM_ISOLATE
  --symbols 159611.SZ 159209.SZ --ws-seconds "$ws_seconds")
if [[ "$quote_only" == true ]]; then
  probe_args+=(--quote-only)
fi
probe_exit=0
result="$("$venv/bin/python" "$stage/probe.py" "${probe_args[@]}" 2>"$stage/probe-stderr")" || probe_exit=$?
if (( probe_exit != 0 )); then
  # Python emits only a fixed schema and exception class on failure. Do not
  # expose traceback, provider response text, URLs, or command arguments.
  failure_class="$(printf '%s\n' "$result" | python3 -c '
import json, re, sys
try:
    value=json.load(sys.stdin).get("failure_class")
except Exception:
    value=None
print(value if isinstance(value,str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}",value) else "UNKNOWN")
' 2>/dev/null)"
  if [[ "$failure_class" == UNKNOWN ]]; then
    # Keep stderr private and inspect only its final exception type. The file
    # is inside the mode-0700 temporary stage and removed by the EXIT trap.
    failure_class="$(python3 - "$stage/probe-stderr" <<'PY'
import os, re, sys
try:
    path=sys.argv[1]
    size=os.path.getsize(path)
    with open(path,"rb") as handle:
        handle.seek(max(0,size-16384))
        tail=handle.read().decode("utf-8","replace")
except Exception:
    tail=""
for line in reversed(tail.splitlines()):
    line=re.sub(r"\x1b\[[0-9;]*m","",line)
    match=re.match(r"^([A-Za-z][A-Za-z0-9_]{0,63})(?::|$)",line)
    if match:
        print(match.group(1))
        break
else:
    print("UNKNOWN")
PY
)"
  fi
  printf 'TICKFLOW_PREMIUM_PROBE_FAILURE_CLASS=%s\n' "$failure_class"
  exit "$probe_exit"
fi
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
allowed_names={"sdk_import","realtime_quote","kline_1m","kline_5m","kline_15m","kline_30m","kline_60m","kline_intraday_15m","kline_intraday_60m","kline_batch_15m","kline_batch_60m","five_level_depth","websocket_quote_smoke"}
allowed_states={"COMPLETED","NO_EVENTS_OBSERVED","OBSERVED","CLOSE_FAILED","FAILED","BLOCKED","SKIPPED","ERROR"}
ops=[]
for raw in d["operations"]:
    assert isinstance(raw,dict) and raw.get("name") in allowed_names
    state=raw.get("operation")
    assert state in allowed_states
    item={"name":raw["name"],"operation":state}
    if raw["name"] in ("kline_15m","kline_60m"):
        item["data_scope"]="HISTORICAL"
    elif raw["name"] in (
        "kline_intraday_15m","kline_intraday_60m",
        "kline_batch_15m","kline_batch_60m",
    ):
        item["data_scope"]="CURRENT_DAY_INTRADAY"
    symbol=raw.get("symbol")
    if symbol in ("159611.SZ","159209.SZ"):
        item["symbol"]=symbol
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
    if raw["name"] in ("kline_batch_15m","kline_batch_60m"):
        batch=raw.get("summary")
        batch=batch if isinstance(batch,dict) else {}
        for field in ("requested_symbol_count","returned_symbol_count",
                      "missing_symbol_count","unrequested_symbol_count"):
            value=batch.get(field)
            item[field]=value if type(value) is int and 0 <= value <= 5 else None
        ceiling=96 if raw["name"] == "kline_batch_15m" else 24
        for source_field,target_field in (
            ("symbol_row_counts","batch_symbol_row_counts"),
            ("symbol_complete_end_sessions","batch_symbol_complete_end_sessions"),
        ):
            values=batch.get(source_field)
            if isinstance(values,list) and len(values) <= 5:
                item[target_field]=[
                    value if type(value) is int and 0 <= value <= (
                        ceiling if source_field == "symbol_row_counts" else 120
                    ) else None
                    for value in values
                ]
            else:
                item[target_field]=[]
        conventions=batch.get("symbol_grid_conventions")
        item["batch_symbol_grid_conventions"]=(
            [value if value in (
                "BAR_END_GRID_MATCH","BAR_START_GRID_MATCH","GRID_CONFLICT",
                "INSUFFICIENT","INVALID_TIMESTAMP_ORDER",
            ) else "INSUFFICIENT" for value in conventions]
            if isinstance(conventions,list) and len(conventions) <= 5 else []
        )
        item["freshness"]="NOT_VERIFIED"
        item["closure"]="NOT_VERIFIED"
        item["provider_live_qualified"]=False
    if raw["name"] in ("kline_15m","kline_60m"):
        # Private raw Kline samples are NEVER exported; even structurally
        # clean historical 15m/60m rows cannot establish live currentness.
        kline=raw.get("summary")
        kline=kline if isinstance(kline,dict) else {}
        value=kline.get("ohlcv_range_valid")
        item["bar_range_structure"]=(
            "PASS" if value is True else "FAIL" if value is False else "NOT_VERIFIED"
        )
        order=kline.get("timestamp_monotonicity")
        item["timestamp_order"]=(
            order if order in (
                "STRICTLY_INCREASING","NON_DECREASING","NOT_MONOTONIC","NOT_VERIFIED"
            ) else "NOT_VERIFIED"
        )
        fields=kline.get("numeric_fields")
        fields=fields if isinstance(fields,dict) else {}
        item["numeric_ohlcv"]=(
            "PASS" if all(fields.get(k) is True for k in (
                "open","high","low","close","volume"
            )) else "NOT_VERIFIED"
        )
        item["numeric_amount"]=(
            "PASS" if fields.get("amount") is True else "NOT_VERIFIED"
        )
        n=kline.get("sample_count")
        item["historical_sample_count"]=(
            n if type(n) is int and 0 <= n <= 96 else None
        )
        grid=kline.get("historical_grid")
        grid=grid if isinstance(grid,dict) else {}
        convention=grid.get("label_convention")
        item["historical_grid_convention"]=(
            convention if convention in (
                "BAR_END_GRID_MATCH","BAR_START_GRID_MATCH","GRID_CONFLICT",
                "INSUFFICIENT","INVALID_TIMESTAMP_ORDER"
            ) else "INSUFFICIENT"
        )
        for field in (
            "prior_sessions_observed","complete_end_sessions",
            "complete_start_sessions","current_day_rows_excluded",
        ):
            value=grid.get(field)
            item["historical_grid_"+field]=(
                value if type(value) is int and 0 <= value <= 120 else None
            )
        item["historical_grid_is_not_closure_proof"]=True
        item["freshness"]="NOT_VERIFIED"
        item["closure"]="NOT_VERIFIED"
        item["provider_live_qualified"]=False
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
