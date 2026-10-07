#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-us-options-intelligence}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-us-options-intelligence.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact collector commit SHA is required}"
OPEND_HOST="${OPEND_HOST:-127.0.0.1}"
OPEND_PORT="${OPEND_PORT:-11111}"
SYMBOLS="${SYMBOLS:-US.QQQ}"
POLL_SECONDS="${POLL_SECONDS:-60}"
OUTPUT_PATH="${OUTPUT_PATH:-/run/stock-razor-us-options-intelligence/options-intelligence.json}"
STATUS_PATH="${STATUS_PATH:-/run/stock-razor-us-options-intelligence/latest-heartbeat.json}"

case "$REPO_REF" in
  (*[!0-9a-f]*|"") echo "REPO_REF must be lowercase hex" >&2; exit 2;;
esac
test "${#REPO_REF}" -eq 40
case "$OPEND_HOST" in
  (127.0.0.1) ;;
  (*) echo "OPEND_HOST must remain 127.0.0.1" >&2; exit 2;;
esac
case "$OPEND_PORT" in
  (*[!0-9]*|"") echo "OPEND_PORT must be numeric" >&2; exit 2;;
esac
test "$OPEND_PORT" -ge 1
test "$OPEND_PORT" -le 65535
test "$(id -u)" -eq 0
command -v git >/dev/null
command -v python3 >/dev/null
command -v systemctl >/dev/null


install -d -m 0755 "$INSTALL_ROOT"
if [ ! -d "$INSTALL_ROOT/repo/.git" ]; then
  git clone --filter=blob:none "$REPO_URL" "$INSTALL_ROOT/repo"
fi
git -C "$INSTALL_ROOT/repo" fetch --depth=1 origin "$REPO_REF"
git -C "$INSTALL_ROOT/repo" checkout --detach "$REPO_REF"
test "$(git -C "$INSTALL_ROOT/repo" rev-parse HEAD)" = "$REPO_REF"

if [ ! -x "$INSTALL_ROOT/venv/bin/python" ]; then
  python3 -m venv "$INSTALL_ROOT/venv"
fi
"$INSTALL_ROOT/venv/bin/pip" install --disable-pip-version-check --no-input \
  'numpy==1.26.4' \
  'pandas==2.2.2' \
  'exchange-calendars==4.13.2' \
  'futu-api==10.8.6808'

PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<'PY'
from src.services.options_intelligence.collector import (
    build_futu_options_intelligence_packet,
    resolve_us_options_session_context,
)
from src.services.options_intelligence.collector_runtime import (
    run_options_collection_cycle,
)
from src.services.options_intelligence.futu_opend_source import (
    FutuOpenDOptionsSource,
)
from src.services.options_intelligence.runtime_snapshot import (
    write_options_intelligence_runtime_snapshot,
)
print("US_OPTIONS_INTELLIGENCE_IMPORT_SMOKE=PASS")
PY


cat >"$INSTALL_ROOT/run.py" <<'PY'
import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

from src.services.options_intelligence.collector import (
    resolve_us_options_session_context,
)
from src.services.options_intelligence.collector_runtime import (
    CollectorCycleResult,
    run_options_collection_cycle,
    safe_exception_code,
)
from src.services.options_intelligence.futu_opend_source import (
    FutuOpenDOptionsSource,
)

repo_sha = os.environ["STOCK_RAZOR_OPTIONS_REPO_SHA"].strip().lower()
opend_host = os.environ.get("STOCK_RAZOR_OPEND_HOST", "127.0.0.1").strip()
opend_port = int(os.environ.get("STOCK_RAZOR_OPEND_PORT", "11111"))
symbols = tuple(
    item.strip().upper()
    for item in os.environ.get("STOCK_RAZOR_OPTIONS_SYMBOLS", "US.QQQ").split(",")
    if item.strip()
)
poll_seconds = max(
    30.0,
    float(os.environ.get("STOCK_RAZOR_OPTIONS_POLL_SECONDS", "60")),
)
output_path = os.environ.get(
    "STOCK_RAZOR_OPTIONS_OUTPUT_PATH",
    "/run/stock-razor-us-options-intelligence/options-intelligence.json",
)
status_path = os.environ.get(
    "STOCK_RAZOR_OPTIONS_STATUS_PATH",
    "/run/stock-razor-us-options-intelligence/latest-heartbeat.json",
)
runtime_id = os.environ.get("STOCK_RAZOR_RUNTIME_ID") or str(uuid.uuid4())
host_id = socket.gethostname()
sequence = 0


if not symbols:
    raise SystemExit("STOCK_RAZOR_OPTIONS_SYMBOLS must contain at least one symbol")
if opend_host != "127.0.0.1":
    raise SystemExit("STOCK_RAZOR_OPEND_HOST must remain 127.0.0.1")


def publish(payload):
    directory = os.path.dirname(status_path)
    os.makedirs(directory, exist_ok=True)
    temporary = status_path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, status_path)


while True:
    sequence += 1
    now = datetime.now(timezone.utc)
    session = resolve_us_options_session_context(now)
    stage = "source_construct"
    try:
        source = FutuOpenDOptionsSource(
            host=opend_host,
            port=opend_port,
            chain_days=7,
            snapshot_batch_size=200,
        )
        if session.status == "READY":
            stage = "opend_context_init"
            with source:
                stage = "collection_cycle"
                result = run_options_collection_cycle(
                    source,
                    symbols,
                    evaluated_at=now,
                    runtime_instance_id=runtime_id,
                    repo_sha=repo_sha,
                    sequence=sequence,
                    output_path=output_path,
                )
        else:
            stage = "blocked_phase_cycle"
            result = run_options_collection_cycle(
                source,
                symbols,
                evaluated_at=now,
                runtime_instance_id=runtime_id,
                repo_sha=repo_sha,
                sequence=sequence,
                output_path=output_path,
            )
        stage = "serialize_cycle"
        cycle_payload = result.to_dict()
    except Exception as exc:
        cycle_payload = {
            "status": "BLOCKED",
            "evaluated_at": now.isoformat(),
            "sequence": sequence,
            "phase": session.phase,
            "snapshot_written": False,
            "output_path": output_path,
            "packets_written": 0,
            "symbols": [],
            "reasons": [f"COLLECTOR_RUNTIME_ERROR:{stage}:{safe_exception_code(exc)}"],
            "research_only": True,
            "trading_authority": False,
            "live_trade": False,
        }

    heartbeat = {
        "type": "us_options_intelligence_heartbeat",
        "runtime_instance_id": runtime_id,
        "repo_sha": repo_sha,
        "host_id": host_id,
        "sequence": sequence,
        "emitted_at_utc": now.isoformat(),
        "symbols": list(symbols),
        "opend_host": opend_host,
        "opend_port": opend_port,
        "cycle": cycle_payload,
        "research_only": True,
        "trading_authority": False,
        "live_trade": False,
    }
    publish(heartbeat)
    print(json.dumps(heartbeat, separators=(",", ":"), allow_nan=False), flush=True)
    time.sleep(poll_seconds)
PY


cat >/etc/systemd/system/"$SERVICE_NAME" <<EOF
[Unit]
Description=STOCK RAZOR research-only US options intelligence collector
After=stock-razor-us-livefeed.service
Wants=stock-razor-us-livefeed.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONPATH=$INSTALL_ROOT/repo
Environment=STOCK_RAZOR_OPTIONS_REPO_SHA=$REPO_REF
Environment=STOCK_RAZOR_OPEND_HOST=$OPEND_HOST
Environment=STOCK_RAZOR_OPEND_PORT=$OPEND_PORT
Environment=STOCK_RAZOR_OPTIONS_SYMBOLS=$SYMBOLS
Environment=STOCK_RAZOR_OPTIONS_POLL_SECONDS=$POLL_SECONDS
Environment=STOCK_RAZOR_OPTIONS_OUTPUT_PATH=$OUTPUT_PATH
Environment=STOCK_RAZOR_OPTIONS_STATUS_PATH=$STATUS_PATH
RuntimeDirectory=stock-razor-us-options-intelligence
RuntimeDirectoryMode=0700
ExecStart=$INSTALL_ROOT/venv/bin/python $INSTALL_ROOT/run.py
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
RestrictSUIDSGID=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
IPAddressDeny=any
IPAddressAllow=localhost

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
