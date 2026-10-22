#!/usr/bin/env bash
set -euo pipefail
umask 077
REPO_REF="${REPO_REF:?exact SHA required}"
[[ "$REPO_REF" =~ ^[0-9a-f]{40}$ ]]
[[ "$(id -u)" == 0 ]]
DEPLOY_DRY_RUN="${DEPLOY_DRY_RUN:-false}"
ALLOW_SERVICE_MUTATION="${ALLOW_SERVICE_MUTATION:-false}"
# The production default is a bounded 200-symbol A-share scan. Operators may
# replace it explicitly, while the worker still hard-caps every scan at 200.
TICKFLOW_RESEARCH_SYMBOLS="${TICKFLOW_RESEARCH_SYMBOLS:-AUTO_200}"
ROOT=/opt/stock-razor-cn-tickflow
SERVICE=stock-razor-cn-tickflow-research.service
REPO=https://github.com/kaku3030/stock-razor.git
install -d -m 0755 "$ROOT"
if [[ ! -d "$ROOT/repo/.git" ]]; then
  git clone --filter=blob:none "$REPO" "$ROOT/repo" >/dev/null 2>&1
fi
previous_sha="$(git -C "$ROOT/repo" rev-parse HEAD 2>/dev/null || true)"
previous_active="false"
if systemctl is-active --quiet "$SERVICE"; then previous_active="true"; fi
failure_stage="INITIALIZE"

if [[ "$DEPLOY_DRY_RUN" == "true" ]]; then
  [[ "$ALLOW_SERVICE_MUTATION" != "true" ]]
  echo "CN_TICKFLOW_DEPLOY_DRY_RUN=PASS"
  echo "CN_TICKFLOW_PREVIOUS_REPO_SHA=${previous_sha:-UNKNOWN}"
  echo "CN_TICKFLOW_SERVICE_MUTATION=NO"
  echo "SOURCE_ARBITER_ADMISSION=BLOCKED"
  echo "RADAR_ADMISSION=BLOCKED"
  echo "LIVE_TRADE=NO"
  exit 0
fi
[[ "$ALLOW_SERVICE_MUTATION" == "true" ]]

# Preserve the existing isolated unit's exact revision pin before any
# installer changes. Rollback must restore BOTH git code and unit environment.
unit_file="/etc/systemd/system/$SERVICE"
unit_backup=""
if [[ -f "$unit_file" ]]; then
  unit_backup="$(mktemp -t sr-cn-tickflow-research-unit.XXXXXXXX)"
  cp -p -- "$unit_file" "$unit_backup"
fi
trap 'if [[ -n "${unit_backup:-}" ]]; then rm -f -- "$unit_backup"; fi' EXIT

rollback() {
  local rc=$?
  trap - ERR
  if [[ "$rc" -ne 0 ]]; then
    if [[ -n "$unit_backup" && -f "$unit_backup" ]]; then
      cp -p -- "$unit_backup" "$unit_file" >/dev/null 2>&1 || true
    elif [[ -z "$unit_backup" ]]; then
      rm -f -- "$unit_file" >/dev/null 2>&1 || true
    fi
    if [[ "$previous_sha" =~ ^[0-9a-f]{40}$ ]]; then
      git -C "$ROOT/repo" checkout --detach "$previous_sha" >/dev/null 2>&1 || true
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
    if [[ "$previous_active" == "true" ]]; then
      systemctl restart "$SERVICE" >/dev/null 2>&1 || true
    fi
    echo "CN_TICKFLOW_INSTALL_FAILED_STAGE=$failure_stage" >&2
    echo "CN_TICKFLOW_ROLLBACK=ATTEMPTED" >&2
  fi
  return "$rc"
}
trap rollback ERR
failure_stage="GIT_FETCH"
git -C "$ROOT/repo" fetch --depth=1 origin "$REPO_REF" >/dev/null 2>&1
failure_stage="GIT_CHECKOUT"
git -C "$ROOT/repo" checkout --detach "$REPO_REF" >/dev/null 2>&1
failure_stage="CHECKOUT_SHA_ASSERT"
[[ "$(git -C "$ROOT/repo" rev-parse HEAD)" == "$REPO_REF" ]]
failure_stage="CREATE_VENV"
if [[ ! -x "$ROOT/venv/bin/python" ]]; then python3 -m venv "$ROOT/venv"; fi
if [[ "$TICKFLOW_RESEARCH_SYMBOLS" == AUTO_200 ]]; then
  failure_stage="RESOLVE_SYMBOLS"
  TICKFLOW_RESEARCH_SYMBOLS="$(PYTHONPATH="$ROOT/repo" "$ROOT/venv/bin/python" - "$ROOT/repo/apps/dsa-web/public/stocks.index.json" <<'PY'
import json
import re
import sys

from data_provider.cn_tickflow_research_cache import MAX_SCAN_SYMBOLS, SYMBOLS

path = sys.argv[1]
rows = json.load(open(path, encoding="utf-8"))
# Reserve the shared baseline before filling bounded active-stock candidates.
symbols = list(SYMBOLS)
for row in rows:
    if not isinstance(row, list) or len(row) < 9:
        continue
    symbol, market, asset_type = row[0], row[6], row[7]
    if (market == "CN" and asset_type == "stock" and row[8] is True
            and isinstance(symbol, str)
            and re.fullmatch(r"[0-9]{6}\.(?:SH|SZ)", symbol)):
        symbols.append(symbol)
symbols = list(dict.fromkeys(symbols))[:MAX_SCAN_SYMBOLS]
if len(symbols) != MAX_SCAN_SYMBOLS:
    raise SystemExit("CN stock index cannot fill scan after reserving baseline")
print(",".join(symbols))
PY
)"
fi
failure_stage="PIP_INSTALL"
# The requirements file owns the boto3/botocore version pair; do not override it here.
"$ROOT/venv/bin/pip" install --no-input --disable-pip-version-check --quiet \
  -r "$ROOT/repo/ops/requirements/tickflow-isolated-v0.1.txt" >/dev/null 2>&1
failure_stage="IMPORT_ASSERTIONS"
PYTHONPATH="$ROOT/repo" "$ROOT/venv/bin/python" - <<'PY' >/dev/null
from data_provider.cn_tickflow_research_cache import DEFAULT_PATH,SCHEMA,normalize_bars
from scripts.run_cn_tickflow_research_worker import _interval
assert DEFAULT_PATH=="/run/stock-razor-cn-tickflow/latest-research-observation.json"
assert SCHEMA=="stock_razor_cn_tickflow_research_observation_v0_1"
assert callable(normalize_bars) and callable(_interval)
import importlib.metadata as m
assert m.version("tickflow")=="0.1.25"
assert m.version("boto3")=="1.43.114"
PY
failure_stage="WRITE_SYSTEMD_UNIT"
cat >"/etc/systemd/system/$SERVICE" <<EOF
[Unit]
Description=STOCK RAZOR CN TickFlow Premium isolated research-only minute cache
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=900
StartLimitBurst=4

[Service]
Type=simple
WorkingDirectory=$ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONPATH=$ROOT/repo
Environment=STOCK_RAZOR_REPO_SHA=$REPO_REF
Environment=STOCK_RAZOR_CN_TICKFLOW_STATUS_PATH=/run/stock-razor-cn-tickflow/latest-research-observation.json
Environment=TICKFLOW_RESEARCH_SYMBOLS=$TICKFLOW_RESEARCH_SYMBOLS
RuntimeDirectory=stock-razor-cn-tickflow
RuntimeDirectoryMode=0700
ExecStart=$ROOT/venv/bin/python -m scripts.run_cn_tickflow_research_worker
Restart=on-failure
RestartSec=180
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
failure_stage="SYSTEMD_DAEMON_RELOAD"
systemctl daemon-reload
failure_stage="SYSTEMD_ENABLE"
systemctl enable "$SERVICE" >/dev/null
failure_stage="SYSTEMD_RESTART"
systemctl restart "$SERVICE"
failure_stage="SYSTEMD_ACTIVE_CHECK"
systemctl is-active "$SERVICE"
failure_stage="COMPLETED"
echo "CN_TICKFLOW_RESEARCH_SERVICE_DEPLOY=PASS"
echo "CN_TICKFLOW_PREVIOUS_REPO_SHA=${previous_sha:-UNKNOWN}"
echo "CN_TICKFLOW_TARGET_REPO_SHA=$REPO_REF"
echo "CN_TICKFLOW_SERVICE_MUTATION=APPLIED"
echo "SOURCE_ARBITER_ADMISSION=BLOCKED"
echo "RADAR_ADMISSION=BLOCKED"
echo "LIVE_TRADE=NO"
