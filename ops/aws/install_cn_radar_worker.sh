#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-cn-radar}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-cn-radar.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact worker commit SHA is required}"
SOURCE_REPO_SHA="${SOURCE_REPO_SHA:?SOURCE_REPO_SHA exact CN observation commit SHA is required}"
SOURCE_PATH="${SOURCE_PATH:-/run/stock-razor-cn-eastmoney/latest-observation.json}"
STATUS_PATH="${STATUS_PATH:-/run/stock-razor-cn-radar/latest-research-state.json}"

for value in "$REPO_REF" "$SOURCE_REPO_SHA"; do
  case "$value" in
    (*[!0-9a-f]*|"") echo "exact lowercase git SHA required" >&2; exit 2;;
  esac
  test "${#value}" -eq 40
done
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
"$INSTALL_ROOT/venv/bin/pip" install --disable-pip-version-check --no-input   'numpy==1.26.4' 'pandas==2.2.2' 'PyYAML==6.0.2'

PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<'PY'
from src.services.stock_radar_v2.cn_observation_analysis import evaluate_cn_observation_payload
from src.services.stock_radar_v2.cn_observation_worker import CnObservationRadarWorker
assert evaluate_cn_observation_payload is not None
assert CnObservationRadarWorker is not None
print("CN_RADAR_WORKER_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

from src.services.stock_radar_v2.cn_observation_worker import CnObservationRadarWorker

worker_repo_sha = os.environ["STOCK_RAZOR_WORKER_REPO_SHA"].strip().lower()
expected_source_repo_sha = os.environ["STOCK_RAZOR_SOURCE_REPO_SHA"].strip().lower()
source_path = os.environ.get(
    "STOCK_RAZOR_CN_OBSERVATION_PATH",
    "/run/stock-razor-cn-eastmoney/latest-observation.json",
)
status_path = os.environ.get(
    "STOCK_RAZOR_CN_RADAR_STATUS_PATH",
    "/run/stock-razor-cn-radar/latest-research-state.json",
)
poll_seconds = max(
    1.0,
    float(os.environ.get("STOCK_RAZOR_CN_RADAR_POLL_SECONDS", "5")),
)
runtime_id = os.environ.get("STOCK_RAZOR_RUNTIME_ID") or str(uuid.uuid4())
host_id = socket.gethostname()
worker = CnObservationRadarWorker(
    expected_source_repo_sha=expected_source_repo_sha,
    max_source_age_seconds=180,
)
sequence = 0


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
    evaluation = worker.poll_file(source_path)
    sequence += 1
    payload = {
        "type": "cn_radar_research_heartbeat",
        "runtime_instance_id": runtime_id,
        "worker_repo_sha": worker_repo_sha,
        "expected_source_repo_sha": expected_source_repo_sha,
        "host_id": host_id,
        "sequence": sequence,
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": source_path,
        "evaluation": evaluation,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    publish(payload)
    print(json.dumps(payload, separators=(",", ":"), allow_nan=False), flush=True)
    time.sleep(poll_seconds)
PY

cat >/etc/systemd/system/"$SERVICE_NAME" <<EOF
[Unit]
Description=STOCK RAZOR isolated CN Radar research worker
After=stock-razor-cn-eastmoney.service
Wants=stock-razor-cn-eastmoney.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$INSTALL_ROOT/repo
Environment=STOCK_RAZOR_WORKER_REPO_SHA=$REPO_REF
Environment=STOCK_RAZOR_SOURCE_REPO_SHA=$SOURCE_REPO_SHA
Environment=STOCK_RAZOR_CN_OBSERVATION_PATH=$SOURCE_PATH
Environment=STOCK_RAZOR_CN_RADAR_STATUS_PATH=$STATUS_PATH
Environment=STOCK_RAZOR_CN_RADAR_POLL_SECONDS=5
RuntimeDirectory=stock-razor-cn-radar
RuntimeDirectoryMode=0755
ExecStart=$INSTALL_ROOT/venv/bin/python $INSTALL_ROOT/run.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
PrivateNetwork=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/run/stock-razor-cn-eastmoney

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
