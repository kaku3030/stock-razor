#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-cn-eastmoney}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-cn-eastmoney.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"
STATUS_PATH="${STATUS_PATH:-/run/stock-razor-cn-eastmoney/latest-observation.json}"
SYMBOLS="${SYMBOLS:-512730,159611,159363}"
POLL_SECONDS="${POLL_SECONDS:-60}"

case "$REPO_REF" in
  (*[!0-9a-f]*|"") echo "REPO_REF must be lowercase hex" >&2; exit 2;;
esac
test "${#REPO_REF}" -eq 40
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

PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<'PY'
from data_provider.cn_eastmoney_cloud_observer import (
    build_cn_cloud_observation,
    build_kline_url,
)
assert "push2his.eastmoney.com" in build_kline_url("512730", "15m")
print("CN_EASTMONEY_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

from data_provider.cn_eastmoney_cloud_observer import build_cn_cloud_observation

repo_sha = os.environ["STOCK_RAZOR_REPO_SHA"].strip().lower()
status_path = os.environ.get(
    "STOCK_RAZOR_CN_EASTMONEY_STATUS_PATH",
    "/run/stock-razor-cn-eastmoney/latest-observation.json",
)
symbols = tuple(
    dict.fromkeys(
        item.strip()
        for item in os.environ.get(
            "STOCK_RAZOR_CN_SYMBOLS",
            "512730,159611,159363",
        ).split(",")
        if item.strip()
    )
)
poll_seconds = max(
    30.0,
    float(os.environ.get("STOCK_RAZOR_CN_POLL_SECONDS", "60")),
)
runtime_id = os.environ.get("STOCK_RAZOR_RUNTIME_ID") or str(uuid.uuid4())
host_id = socket.gethostname()
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
    sequence += 1
    observed_at = datetime.now(timezone.utc)
    try:
        payload = build_cn_cloud_observation(
            symbols,
            repo_sha=repo_sha,
            runtime_instance_id=runtime_id,
            sequence=sequence,
            observed_at_utc=observed_at,
        )
    except Exception as exc:
        payload = {
            "schema": "stock_razor_cn_eastmoney_observation_v1",
            "repo_sha": repo_sha,
            "runtime_instance_id": runtime_id,
            "sequence": sequence,
            "emitted_at_utc": observed_at.isoformat(),
            "status": "BLOCKED",
            "error": type(exc).__name__,
            "symbols": {},
            "provider": "eastmoney",
            "provider_lineage": "eastmoney",
            "intraday_timestamp_semantics_proven": False,
            "intraday_currentness_proven": False,
            "research_only": True,
            "can_confirm_signal": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }
    payload["host_id"] = host_id
    publish(payload)
    print(json.dumps(payload, separators=(",", ":"), allow_nan=False), flush=True)
    time.sleep(poll_seconds)
PY

cat >/etc/systemd/system/"$SERVICE_NAME" <<EOF
[Unit]
Description=STOCK RAZOR A-share Eastmoney cloud observation service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$INSTALL_ROOT/repo
Environment=STOCK_RAZOR_REPO_SHA=$REPO_REF
Environment=STOCK_RAZOR_CN_EASTMONEY_STATUS_PATH=$STATUS_PATH
Environment=STOCK_RAZOR_CN_SYMBOLS=$SYMBOLS
Environment=STOCK_RAZOR_CN_POLL_SECONDS=$POLL_SECONDS
RuntimeDirectory=stock-razor-cn-eastmoney
RuntimeDirectoryMode=0755
ExecStart=$INSTALL_ROOT/venv/bin/python $INSTALL_ROOT/run.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
