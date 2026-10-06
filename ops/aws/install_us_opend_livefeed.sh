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
from src.services.live_feed.canonical_snapshot_export import build_canonical_snapshot_export
from src.services.live_feed.futu_k1m_closure_pipeline import FutuK1MClosurePipeline
from src.services.live_feed.futu_k1m_research_consumer import FutuK1MResearchConsumer
from src.services.realtime_market_data import RealtimeMarketDataService
print("US_LIVEFEED_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json, os, socket, threading, time, uuid
from datetime import datetime, timezone
import futu as ft
from data_provider.futu_k1m_streaming_adapter import (
    FutuK1MStreamingAdapter,
    OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE,
)
from data_provider.live_feed_types import ProviderEventKind, SemanticStreamKey
from data_provider.market_data_adapter import evaluate_health
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import LiveFeedController
from src.services.live_feed.canonical_snapshot_export import (
    SCHEMA as CANONICAL_SNAPSHOT_SCHEMA,
    build_canonical_snapshot_export,
    write_canonical_snapshot_export,
)
from src.services.live_feed.futu_k1m_closure_pipeline import FutuK1MClosurePipeline
from src.services.live_feed.futu_k1m_currentness import (
    classify_futu_us_k1m_currentness,
    futu_us_market_state_to_session,
    summarize_futu_k1m_currentness,
)
from src.services.live_feed.futu_k1m_research_consumer import FutuK1MResearchConsumer
from src.services.live_feed.runtime_bridge import LiveFeedRuntimeBridge
from src.services.realtime_market_data import RealtimeMarketDataService

CODES=("US.AMD","US.NVDA","US.TSLA","US.AAPL","US.QQQ")
runtime_id=os.environ.get("STOCK_RAZOR_RUNTIME_ID") or str(uuid.uuid4())
repo_sha=os.environ["STOCK_RAZOR_REPO_SHA"]
status_path=os.environ.get("STOCK_RAZOR_US_LIVEFEED_STATUS_PATH","/run/stock-razor-us-livefeed/latest-heartbeat.json")
canonical_snapshot_path=os.environ.get(
    "STOCK_RAZOR_CANONICAL_SNAPSHOT_PATH",
    "/run/stock-razor-us-livefeed/canonical-market-snapshot.json",
)
host_id=socket.gethostname()
ctx=ft.OpenQuoteContext(host="127.0.0.1",port=11111)
controller=LiveFeedController(runtime_instance_id=runtime_id,provider_id="futu",command_executor=FakeProviderCommandExecutor())
market_state_us="UNKNOWN"
blocked_provider_health=evaluate_health(
    freshness=0.0,completeness=0.0,timestamp=0.0,provider=1.0,continuity=0.0,cross_check=0.0,
    quality_flags=("MISSING_BAR","TIMESTAMP_SEMANTICS_UNVERIFIED"),
)
market_data=RealtimeMarketDataService(
    None,
    session_status_provider=lambda _market: futu_us_market_state_to_session(market_state_us),
    provider_health_provider=lambda: blocked_provider_health,
    max_minutes=480,
)
closure_pipeline=FutuK1MClosurePipeline(max_pending_closed=1024)
research_consumer=FutuK1MResearchConsumer(controller,closure_pipeline,market_data)
accepted_event_count=0
data_event_count=0
last_push_utc=None
latest_time_keys={}
evidence_lock=threading.Lock()
def generation(): return controller.snapshot().controller_generation
adapter=FutuK1MStreamingAdapter(
    ctx,ft,runtime_instance_id=runtime_id,controller_generation=generation,
    # futu-api 10.11.7108: default is_async_connect=False returns only
    # after _init_connect_sync() reports RET_OK. Transport evidence only.
    transport_connected_evidence=OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE,
)
def on_event_accepted(event):
    global accepted_event_count,data_event_count,last_push_utc
    with evidence_lock:
        accepted_event_count+=1
        if event.event_kind is ProviderEventKind.DATA:
            data_event_count+=1
            last_push_utc=datetime.now(timezone.utc).isoformat()
            key=event.semantic_stream_key
            if key is not None and event.provider_timestamp_raw:
                latest_time_keys[key.symbol]=str(event.provider_timestamp_raw)
bridge=LiveFeedRuntimeBridge(controller,adapter,on_event_accepted=on_event_accepted)
streams=[SemanticStreamKey("futu","us",c,"K_1M","1m") for c in CODES]
bridge.start(streams)
seq=0
canonical_export_sequence=0
canonical_export_status="UNKNOWN"
canonical_export_error=None
canonical_export_last_write_utc=None
last_export_market_state=None
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
        state_ret,state_data=ctx.get_global_state()
        market_state=(str(state_data.get("market_us") or "UNKNOWN")
                      if state_ret==ft.RET_OK and isinstance(state_data,dict) else "UNKNOWN")
        market_state_us=market_state
        cache_session=futu_us_market_state_to_session(market_state)
        snap=bridge.drain()
        consumer_result=research_consumer.run_once(max_events=1000)
        seq+=1; now=datetime.now(timezone.utc)
        with evidence_lock:
            data_count=data_event_count
            accepted_count=accepted_event_count
            push_utc=last_push_utc
            time_keys=dict(latest_time_keys)
        currentness={
            code:classify_futu_us_k1m_currentness(
                time_keys.get(code),observed_at_utc=now,market_state=market_state
            )
            for code in CODES
        }
        currentness_payload={
            code:{
                "status":result.status,
                "reason":result.reason,
                "time_key":time_keys.get(code),
                "age_seconds":result.age_seconds,
                "interval_start_utc":(
                    result.interval_start_utc.isoformat()
                    if result.interval_start_utc else None
                ),
                "interval_end_utc":(
                    result.interval_end_utc.isoformat()
                    if result.interval_end_utc else None
                ),
                "end_offset_seconds":result.end_offset_seconds,
            }
            for code,result in currentness.items()
        }
        currentness_summary=summarize_futu_k1m_currentness(currentness)
        canonical_cache={}
        canonical_snapshots={}
        for code in CODES:
            cache_snapshot=market_data.snapshot(code,as_of=now)
            canonical_snapshots[code]=cache_snapshot
            bars_1m=cache_snapshot.minute_bars
            bars_5m=cache_snapshot.bars_5m
            bars_15m=cache_snapshot.bars_15m
            bars_1h=cache_snapshot.bars_1h
            latest_1m=bars_1m[-1] if bars_1m else None
            latest_5m=bars_5m[-1] if bars_5m else None
            latest_15m=bars_15m[-1] if bars_15m else None
            latest_1h=bars_1h[-1] if bars_1h else None
            canonical_cache[code]={
                "bar_count":len(bars_1m),
                "latest_bar_start_utc":latest_1m.bar_start.isoformat() if latest_1m else None,
                "latest_bar_end_utc":latest_1m.bar_end.isoformat() if latest_1m else None,
                "bar_count_5m":len(bars_5m),
                "latest_5m_end_utc":latest_5m.bar_end.isoformat() if latest_5m else None,
                "bar_count_15m":len(bars_15m),
                "latest_15m_end_utc":latest_15m.bar_end.isoformat() if latest_15m else None,
                "bar_count_1h":len(bars_1h),
                "latest_1h_end_utc":latest_1h.bar_end.isoformat() if latest_1h else None,
            }
        canonical_export_updated=False
        should_export=(
            consumer_result.bars_ingested > 0
            or not os.path.exists(canonical_snapshot_path)
            or market_state != last_export_market_state
            or canonical_export_status != "PASS"
        )
        if should_export:
            try:
                next_export_sequence=canonical_export_sequence+1
                canonical_export=build_canonical_snapshot_export(
                    canonical_snapshots,
                    runtime_instance_id=runtime_id,
                    repo_sha=repo_sha,
                    sequence=next_export_sequence,
                    emitted_at_utc=now,
                    market_state_us=market_state,
                    cache_session_us=cache_session,
                )
                write_canonical_snapshot_export(canonical_snapshot_path,canonical_export)
                canonical_export_sequence=next_export_sequence
                canonical_export_status="PASS"
                canonical_export_error=None
                canonical_export_last_write_utc=now.isoformat()
                last_export_market_state=market_state
                canonical_export_updated=True
            except Exception as exc:
                canonical_export_status="BLOCKED"
                canonical_export_error=type(exc).__name__
        closure_diagnostics=closure_pipeline.diagnostics()
        consumer_payload={
            "evidence_processed":consumer_result.evidence_processed,
            "closure_blocked":consumer_result.closure_blocked,
            "bars_ingested":consumer_result.bars_ingested,
            "bars_unchanged":consumer_result.bars_unchanged,
            "stopped_reason":consumer_result.stopped_reason,
            "recent_errors":research_consumer.diagnostics(),
        }
        heartbeat={"type":"us_opend_livefeed_heartbeat","runtime_instance_id":runtime_id,
          "repo_sha":repo_sha,"host_id":host_id,"sequence":seq,"emitted_at_utc":now.isoformat(),
          "symbols":list(CODES),"subscribed":[k.symbol for k in snap.subscribed],
          "controller_lifecycle":snap.controller.lifecycle_state.value,
          "controller_failure_class":snap.controller.failure_class.value,
          "controller_findings_tail":list(snap.controller.findings[-20:]),
          "event_count":data_count,"accepted_event_count":accepted_count,
          "last_push_utc":push_utc,"market_state_us":market_state,
          "cache_session_us":cache_session,
          "market_state_evidence":"PASS" if state_ret==ft.RET_OK else "BLOCKED",
          "latest_k1m_time_keys":time_keys,"k1m_currentness":currentness_payload,
          "k1m_currentness_summary":currentness_summary,
          "closure_pipeline":closure_diagnostics,
          "research_consumer":consumer_payload,
          "canonical_cache":canonical_cache,
          "canonical_snapshot_export":{
              "status":canonical_export_status,
              "error":canonical_export_error,
              "schema":CANONICAL_SNAPSHOT_SCHEMA,
              "path":canonical_snapshot_path,
              "sequence":canonical_export_sequence,
              "updated":canonical_export_updated,
              "last_write_utc":canonical_export_last_write_utc,
              "repo_sha":repo_sha,
          },
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
Environment=STOCK_RAZOR_CANONICAL_SNAPSHOT_PATH=/run/stock-razor-us-livefeed/canonical-market-snapshot.json
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
