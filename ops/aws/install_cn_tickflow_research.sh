#!/usr/bin/env bash
set -euo pipefail
umask 077
REPO_REF="${REPO_REF:?exact SHA required}"
[[ "$REPO_REF" =~ ^[0-9a-f]{40}$ ]]
[[ "$(id -u)" == 0 ]]
ROOT=/opt/stock-razor-cn-tickflow
SERVICE=stock-razor-cn-tickflow-research.service
REPO=https://github.com/kaku3030/stock-razor.git
install -d -m 0755 "$ROOT"
if [[ ! -d "$ROOT/repo/.git" ]]; then
  git clone --filter=blob:none "$REPO" "$ROOT/repo" >/dev/null 2>&1
fi
git -C "$ROOT/repo" fetch --depth=1 origin "$REPO_REF" >/dev/null 2>&1
git -C "$ROOT/repo" checkout --detach "$REPO_REF" >/dev/null 2>&1
[[ "$(git -C "$ROOT/repo" rev-parse HEAD)" == "$REPO_REF" ]]
if [[ ! -x "$ROOT/venv/bin/python" ]]; then python3 -m venv "$ROOT/venv"; fi
"$ROOT/venv/bin/pip" install --no-input --disable-pip-version-check --quiet \
  -r "$ROOT/repo/ops/requirements/tickflow-isolated-v0.1.txt" 'boto3==1.40.65' >/dev/null 2>&1
PYTHONPATH="$ROOT/repo" "$ROOT/venv/bin/python" - <<'PY' >/dev/null
from data_provider.cn_tickflow_research_cache import DEFAULT_PATH,SCHEMA,normalize_bars
from scripts.run_cn_tickflow_research_worker import _interval
assert DEFAULT_PATH=="/run/stock-razor-cn-tickflow/latest-research-observation.json"
assert SCHEMA=="stock_razor_cn_tickflow_research_observation_v0_1"
assert callable(normalize_bars) and callable(_interval)
import importlib.metadata as m
assert m.version("tickflow")=="0.1.25"
assert m.version("boto3")=="1.40.65"
PY
cat >"/etc/systemd/system/$SERVICE" <<EOF
[Unit]
Description=STOCK RAZOR CN TickFlow Premium isolated research-only minute cache
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONPATH=$ROOT/repo
Environment=STOCK_RAZOR_REPO_SHA=$REPO_REF
Environment=STOCK_RAZOR_CN_TICKFLOW_STATUS_PATH=/run/stock-razor-cn-tickflow/latest-research-observation.json
RuntimeDirectory=stock-razor-cn-tickflow
RuntimeDirectoryMode=0700
ExecStart=$ROOT/venv/bin/python -m scripts.run_cn_tickflow_research_worker
Restart=on-failure
RestartSec=15
NoNewPrivileges=true
ProtectHome=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/run/stock-razor-cn-tickflow
MemoryMax=500M
LimitNOFILE=256

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
systemctl is-active "$SERVICE"
echo "CN_TICKFLOW_RESEARCH_SERVICE_DEPLOY=PASS"
echo "SOURCE_ARBITER_ADMISSION=BLOCKED"
echo "RADAR_ADMISSION=BLOCKED"
echo "LIVE_TRADE=NO"

