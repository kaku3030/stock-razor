#!/usr/bin/env bash
set -euo pipefail

# Read-only Futures Runtime V0.1 installer.
# Intentionally separate from stock-razor-mcp.service.
INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-futures}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-futures.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"

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

python3 -m venv "$INSTALL_ROOT/venv"
"$INSTALL_ROOT/venv/bin/pip" install --disable-pip-version-check --no-input   yfinance exchange-calendars pandas

# Fail before systemd installation if the isolated Futures runtime cannot import
# its complete entry-point dependency chain. This catches missing runtime
# dependencies without treating a restart loop as a successful deployment.
PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<'PY'
from data_provider.futures_provider import YahooFuturesHistoryProvider
from data_provider.futures_qualification import FuturesSessionPolicy
from data_provider.futures_runtime_observation import FuturesRuntimeObserver
from data_provider.futures_persistent_worker import FuturesPersistentWorker, WorkerPolicy
print("FUTURES_RUNTIME_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

from data_provider.futures_provider import YahooFuturesHistoryProvider
from data_provider.futures_qualification import FuturesSessionPolicy
from data_provider.futures_runtime_observation import FuturesRuntimeObserver
from data_provider.futures_persistent_worker import FuturesPersistentWorker, WorkerPolicy

runtime_id = os.environ.get("STOCK_RAZOR_RUNTIME_ID") or str(uuid.uuid4())
generation = int(os.environ.get("STOCK_RAZOR_GENERATION", "1"))
host_id = socket.gethostname()
provider = YahooFuturesHistoryProvider(runtime_instance_id=runtime_id, controller_generation=generation)
observer = FuturesRuntimeObserver(
    runtime_instance_id=runtime_id,
    session_policy=FuturesSessionPolicy(),
)
observer.rollover_generation(generation, observed_at_utc=datetime.now(timezone.utc))
worker = FuturesPersistentWorker(
    observer=observer,
    fetch=provider.fetch,
    policy=WorkerPolicy(roots=("GC", "CL", "SI", "HG"), timeframe="5m"),
)

status_path = os.environ.get("STOCK_RAZOR_FUTURES_STATUS_PATH", "/run/stock-razor-futures/latest-heartbeat.json")

def publish_status(payload):
    directory = os.path.dirname(status_path)
    os.makedirs(directory, exist_ok=True)
    tmp = status_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, status_path)

seq = 0
while True:
    now = datetime.now(timezone.utc)
    result = worker.run_cycle(observed_at_utc=now, monotonic_now=time.monotonic())
    seq += 1
    heartbeat = {
        "type": "futures_runtime_heartbeat",
        "runtime_instance_id": runtime_id,
        "generation": generation,
        "host_id": host_id,
        "sequence": seq,
        "emitted_at_utc": now.isoformat(),
        "attempted": result.attempted,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "skipped_backoff": result.skipped_backoff,
        "cloud_runtime_verified": False,
        "pc_off_verified": False,
        "live_trade": False,
    }
    publish_status(heartbeat)
    print(json.dumps(heartbeat, separators=(",", ":")), flush=True)
    time.sleep(60)
PY

cat >/etc/systemd/system/"$SERVICE_NAME" <<EOF
[Unit]
Description=STOCK RAZOR read-only futures runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$INSTALL_ROOT/repo
Environment=STOCK_RAZOR_FUTURES_STATUS_PATH=/run/stock-razor-futures/latest-heartbeat.json
RuntimeDirectory=stock-razor-futures
RuntimeDirectoryMode=0755
ExecStart=$INSTALL_ROOT/venv/bin/python $INSTALL_ROOT/run.py
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
