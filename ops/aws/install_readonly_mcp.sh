#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-mcp}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-mcp.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"

test "$(id -u)" -eq 0
install -d -m 0755 "$INSTALL_ROOT"
if [ ! -d "$INSTALL_ROOT/repo/.git" ]; then
  git clone --filter=blob:none "$REPO_URL" "$INSTALL_ROOT/repo"
fi
git -C "$INSTALL_ROOT/repo" fetch --depth=1 origin "$REPO_REF"
git -C "$INSTALL_ROOT/repo" checkout --detach "$REPO_REF"
test "$(git -C "$INSTALL_ROOT/repo" rev-parse HEAD)" = "$REPO_REF"

python3 -m venv "$INSTALL_ROOT/venv"
"$INSTALL_ROOT/venv/bin/pip" install --disable-pip-version-check --no-input "mcp>=1,<2"

PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<'PY'
from realtime_monitor.readonly_mcp_server import (
    get_cn_market_data,
    get_futures_runtime_health,
    get_livefeed_health,
    get_market_analysis,
    get_market_bars,
    get_market_snapshots,
    mcp,
)
assert mcp is not None
result = get_futures_runtime_health()
assert result["live_trade"] is False
assert result["radar_admission"] == "BLOCKED"
for result in (
    get_cn_market_data("159611", timeframe="1d", limit=1),
    get_livefeed_health(),
    get_market_snapshots(["AMD"]),
    get_market_bars("AMD", timeframe="1m", limit=1),
    get_market_analysis(["AMD"]),
):
    assert result["live_trade"] is False
    assert result["radar_admission"] == "BLOCKED"
print("READONLY_MCP_IMPORT_SMOKE=PASS")
PY

cat >/etc/systemd/system/"$SERVICE_NAME" <<EOF
[Unit]
Description=STOCK RAZOR canonical read-only MCP
After=network-online.target stock-razor-futures.service stock-razor-us-livefeed.service stock-razor-us-radar.service stock-razor-cn-eastmoney.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$INSTALL_ROOT/repo
Environment=STOCK_RAZOR_FUTURES_STATUS_PATH=/run/stock-razor-futures/latest-heartbeat.json
Environment=STOCK_RAZOR_US_LIVEFEED_STATUS_PATH=/run/stock-razor-us-livefeed/latest-heartbeat.json
Environment=STOCK_RAZOR_US_CANONICAL_SNAPSHOT_PATH=/run/stock-razor-us-livefeed/canonical-market-snapshot.json
Environment=STOCK_RAZOR_US_RADAR_STATUS_PATH=/run/stock-razor-us-radar/latest-research-state.json
Environment=STOCK_RAZOR_CN_EASTMONEY_STATUS_PATH=/run/stock-razor-cn-eastmoney/latest-observation.json
ExecStart=$INSTALL_ROOT/venv/bin/python -m realtime_monitor.readonly_mcp_server
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
