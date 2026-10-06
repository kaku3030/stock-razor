#!/usr/bin/env bash
set -euo pipefail
INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-us-livefeed}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-us-livefeed.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"
OPEND_CLIENT_ROOT="${OPEND_CLIENT_ROOT:-/opt/stock-razor-opend-client}"

test "$(id -u)" -eq 0
test -x "$OPEND_CLIENT_ROOT/venv/bin/python"
install -d -m 0755 "$INSTALL_ROOT"
if [ ! -d "$INSTALL_ROOT/repo/.git" ]; then git clone --filter=blob:none "$REPO_URL" "$INSTALL_ROOT/repo"; fi
git -C "$INSTALL_ROOT/repo" fetch --depth=1 origin "$REPO_REF"
git -C "$INSTALL_ROOT/repo" checkout --detach "$REPO_REF"
test "$(git -C "$INSTALL_ROOT/repo" rev-parse HEAD)" = "$REPO_REF"

PYTHONPATH="$INSTALL_ROOT/repo" HOME=/root "$OPEND_CLIENT_ROOT/venv/bin/python" - <<'PY'
import futu
from data_provider.futu_k1m_streaming_adapter import (
    FutuK1MStreamingAdapter,
    OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE,
)
from src.services.live_feed.runtime_bridge import LiveFeedRuntimeBridge
from src.services.live_feed.controller import LiveFeedController
print("US_LIVEFEED_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json, os, socket, time, uuid
from datetime import datetime, timezone
import futu as ft
from data_provider.futu_k1m_streaming_adapter import (
    FutuK1MStreamingAdapter,
    OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE,
)
from data_provider.live_feed_types import ProviderEventKind, SemanticStreamKey
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import LiveFeedController
from src.services.live_feed.runtime_bridge import LiveFeedRuntimeBridge

CODES=("US.AMD","US.NVDA","US.TSLA","US.AAPL","US.QQQ")
runtime_id=os.environ.get("STOCK_RAZOR_RUNTIME_ID") or str(uuid.uuid4())
repo_sha=os.environ["STOCK_RAZOR_REPO_SHA"]
status_path=os.environ.get("STOCK_RAZOR_US_LIVEFEED_STATUS_PATH","/run/stock-razor-us-livefeed/latest-heartbeat.json")
host_id=socket.gethostname()
ctx=ft.OpenQuoteContext(host="127.0.0.1",port=11111)
controller=LiveFeedController(runtime_instance_id=runtime_id,provider_id="futu",command_executor=FakeProviderCommandExecutor())
accepted_event_count=0
data_event_count=0
last_push_utc=None
def generation(): return controller.snapshot().controller_generation
adapter=FutuK1MStreamingAdapter(
    ctx,ft,runtime_instance_id=runtime_id,controller_generation=generation,
    # futu-api 10.11.7108: default is_async_connect=False returns only
    # after _init_connect_sync() reports RET_OK. Transport evidence only.
    transport_connected_evidence=OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE,
)
def on_event_accepted(event):
    global accepted_event_count,data_event_count,last_push_utc
    accepted_event_count+=1
    if event.event_kind is ProviderEventKind.DATA:
        data_event_count+=1
        last_push_utc=datetime.now(timezone.utc).isoformat()
bridge=LiveFeedRuntimeBridge(controller,adapter,on_event_accepted=on_event_accepted)
streams=[SemanticStreamKey("futu","us",c,"K_1M","1m") for c in CODES]
bridge.start(streams)
seq=0
startup_monotonic=time.monotonic()
startup_callback_deadline_seconds=20
def publish(payload):
    os.makedirs(os.path.dirname(status_path),exist_ok=True)
    tmp=status_path+".tmp"
    with open(tmp,"w",encoding="utf-8") as h:
        json.dump(payload,h,separators=(",",":")); h.flush(); os.fsync(h.fileno())
    os.replace(tmp,status_path)
try:
    while True:
        time.sleep(5)
        snap=bridge.drain(); seq+=1; now=datetime.now(timezone.utc)
        heartbeat={"type":"us_opend_livefeed_heartbeat","runtime_instance_id":runtime_id,
          "repo_sha":repo_sha,"host_id":host_id,"sequence":seq,"emitted_at_utc":now.isoformat(),
          "symbols":list(CODES),"subscribed":[k.symbol for k in snap.subscribed],
          "controller_lifecycle":snap.controller.lifecycle_state.value,
          "controller_failure_class":snap.controller.failure_class.value,
          "event_count":data_event_count,"accepted_event_count":accepted_event_count,
          "last_push_utc":last_push_utc,
          "adapter_diagnostics":adapter.diagnostics(),
          "delivery_mode":"UNKNOWN","bar_closure":"UNPROVEN",
          "radar_admission":"BLOCKED","live_trade":False}
        publish(heartbeat); print(json.dumps(heartbeat,separators=(",",":")),flush=True)
        if data_event_count == 0 and (time.monotonic()-startup_monotonic) >= startup_callback_deadline_seconds:
            raise RuntimeError("US_OPEND_STARTUP_CALLBACK_STARVATION")
finally:
    try: bridge.stop()
    finally: ctx.close()
PY

cat >/etc/systemd/system/"$SERVICE_NAME" <<EOF
[Unit]
Description=STOCK RAZOR read-only US OpenD live feed
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$INSTALL_ROOT/repo
Environment=HOME=/root
Environment=STOCK_RAZOR_REPO_SHA=$REPO_REF
Environment=STOCK_RAZOR_US_LIVEFEED_STATUS_PATH=/run/stock-razor-us-livefeed/latest-heartbeat.json
RuntimeDirectory=stock-razor-us-livefeed
RuntimeDirectoryMode=0755
ExecStart=$OPEND_CLIENT_ROOT/venv/bin/python $INSTALL_ROOT/run.py
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
