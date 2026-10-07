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
from src.services.live_feed.futu_k1m_warm_start import build_futu_k1m_warm_start_plan
from src.services.live_feed.futu_quote_right import classify_futu_us_quote_right
from src.services.realtime_market_data import RealtimeMarketDataService
print("US_LIVEFEED_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json, os, socket, threading, time, uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
from src.services.live_feed.futu_k1m_closure_qualification import (
    FutuK1MClosureQualificationTracker,
    derive_futu_k1m_bar_closure_state,
    summarize_futu_k1m_closure_qualification,
)
from src.services.live_feed.futu_k1m_currentness import (
    classify_futu_us_k1m_currentness,
    futu_us_market_state_to_session,
    summarize_futu_k1m_currentness,
)
from src.services.live_feed.futu_k1m_research_consumer import FutuK1MResearchConsumer
from src.services.live_feed.futu_quote_right import classify_futu_us_quote_right
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

warm_start_lookback_days=10
warm_start_max_pages=4
warm_start_payload={}
warm_start_total_seeded=0
def fetch_warm_start_history(code):
    local_today=datetime.now(ZoneInfo("America/New_York")).date()
    start=(local_today-timedelta(days=warm_start_lookback_days)).isoformat()
    end=local_today.isoformat()
    rows=[]
    page_req_key=None
    for page_index in range(warm_start_max_pages):
        ret,data,next_key=ctx.request_history_kline(
            code,
            start=start,
            end=end,
            ktype=ft.KLType.K_1M,
            autype=ft.AuType.NONE,
            max_count=1000,
            page_req_key=page_req_key,
            extended_time=False,
        )
        if ret != ft.RET_OK:
            return (),{
                "status":"BLOCKED",
                "reason":"HISTORY_QUERY_FAILED",
                "page_index":page_index,
            }
        if not hasattr(data,"to_dict"):
            return (),{
                "status":"BLOCKED",
                "reason":"HISTORY_QUERY_INVALID_ROWS",
                "page_index":page_index,
            }
        rows.extend(data.to_dict("records"))
        if not next_key:
            return tuple(rows),{
                "status":"PASS",
                "reason":"BOUNDED_HISTORY_QUERY_COMPLETE",
                "pages":page_index+1,
            }
        page_req_key=next_key
    return (),{
        "status":"BLOCKED",
        "reason":"HISTORY_QUERY_PAGE_LIMIT_REACHED",
        "pages":warm_start_max_pages,
    }

for code in CODES:
    try:
        history_rows,query_evidence=fetch_warm_start_history(code)
        plan=build_futu_k1m_warm_start_plan(
            history_rows,
            received_at=datetime.now(timezone.utc),
            expected_symbol=code,
        )
        seeded=0
        if query_evidence["status"]=="PASS" and plan.research_cache_seed_eligible:
            seeded=sum(1 for bar in plan.bars if market_data.ingest(bar))
        warm_start_total_seeded+=seeded
        warm_start_payload[code]={
            **plan.to_dict(),
            "query_status":query_evidence["status"],
            "query_reason":query_evidence["reason"],
            "query_pages":query_evidence.get("pages"),
            "query_row_count":len(history_rows),
            "bars_ingested":seeded,
        }
    except Exception as exc:
        warm_start_payload[code]={
            "status":"BLOCKED",
            "reason":"WARM_START_EXCEPTION:"+type(exc).__name__,
            "bar_count":0,
            "research_cache_seed_eligible":False,
            "historical_query":True,
            "realtime_currentness_proven":False,
            "bar_closure_promotion_authorized":False,
            "radar_admission":"BLOCKED",
            "live_trade":False,
            "query_status":"BLOCKED",
            "query_reason":"WARM_START_EXCEPTION",
            "query_pages":None,
            "query_row_count":0,
            "bars_ingested":0,
        }
warm_start_pass_count=sum(
    1 for item in warm_start_payload.values()
    if item.get("status")=="PASS" and item.get("bars_ingested")==390
)
warm_start_status=(
    "PASS" if warm_start_pass_count==len(CODES)
    else "PARTIAL" if warm_start_pass_count>0
    else "BLOCKED"
)

closure_pipeline=FutuK1MClosurePipeline(max_pending_closed=1024)
closure_qualification_tracker=FutuK1MClosureQualificationTracker(
    required_consecutive_boundaries=3
)
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
last_export_bar_closure=None
last_export_delivery_mode=None
quote_right_poll_seconds=60.0
quote_right_max_age_seconds=90.0
quote_right_query_status="UNKNOWN"
quote_right_raw="UNKNOWN"
quote_right_observed_at_utc=None
quote_right_query_reason="NOT_QUERIED"
last_quote_right_poll_monotonic=None
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
        monotonic_now=time.monotonic()
        if (
            last_quote_right_poll_monotonic is None
            or (monotonic_now-last_quote_right_poll_monotonic) >= quote_right_poll_seconds
        ):
            last_quote_right_poll_monotonic=monotonic_now
            try:
                qot_ret,qot_data=ctx.get_user_info([ft.UserInfoField.QOTRIGHT])
                if qot_ret==ft.RET_OK and isinstance(qot_data,dict):
                    quote_right_query_status="PASS"
                    quote_right_raw=str(qot_data.get("us_qot_right","UNKNOWN"))
                    quote_right_query_reason="GET_USER_INFO_QOTRIGHT_PASS"
                else:
                    quote_right_query_status="BLOCKED"
                    quote_right_raw="UNKNOWN"
                    quote_right_query_reason="GET_USER_INFO_QOTRIGHT_FAILED"
            except Exception as exc:
                quote_right_query_status="BLOCKED"
                quote_right_raw="UNKNOWN"
                quote_right_query_reason="GET_USER_INFO_QOTRIGHT_ERROR:"+type(exc).__name__
            quote_right_observed_at_utc=datetime.now(timezone.utc)
            now=quote_right_observed_at_utc
        quote_right_age_seconds=(
            (now-quote_right_observed_at_utc).total_seconds()
            if quote_right_observed_at_utc is not None else None
        )
        quote_right_classification=classify_futu_us_quote_right(
            query_status=quote_right_query_status,
            us_qot_right=quote_right_raw,
            age_seconds=quote_right_age_seconds,
            max_age_seconds=quote_right_max_age_seconds,
        )
        delivery_mode_evidence_state=quote_right_classification.delivery_mode
        quote_right_payload=quote_right_classification.to_dict()
        quote_right_payload.update({
            "observed_at_utc":(
                quote_right_observed_at_utc.isoformat()
                if quote_right_observed_at_utc is not None else None
            ),
            "poll_seconds":quote_right_poll_seconds,
            "query_reason":quote_right_query_reason,
        })
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
        closure_qualification={
            code:closure_qualification_tracker.observe(
                code,
                currentness=currentness[code],
                latest_closed_bar=(
                    canonical_snapshots[code].minute_bars[-1]
                    if canonical_snapshots[code].minute_bars else None
                ),
            )
            for code in CODES
        }
        closure_qualification_payload={
            code:{
                "status":result.status,
                "reason":result.reason,
                "consecutive_boundaries":result.consecutive_boundaries,
                "required_consecutive_boundaries":result.required_consecutive_boundaries,
                "interval_start_utc":(
                    result.interval_start_utc.isoformat()
                    if result.interval_start_utc else None
                ),
                "interval_end_utc":(
                    result.interval_end_utc.isoformat()
                    if result.interval_end_utc else None
                ),
                "latest_closed_bar_start_utc":(
                    result.latest_closed_bar_start_utc.isoformat()
                    if result.latest_closed_bar_start_utc else None
                ),
                "latest_closed_bar_end_utc":(
                    result.latest_closed_bar_end_utc.isoformat()
                    if result.latest_closed_bar_end_utc else None
                ),
                "latest_closed_bar_source_timestamp_utc":(
                    result.latest_closed_bar_source_timestamp_utc.isoformat()
                    if result.latest_closed_bar_source_timestamp_utc else None
                ),
                "boundary_delta_seconds":result.boundary_delta_seconds,
                "can_promote":result.can_promote,
            }
            for code,result in closure_qualification.items()
        }
        closure_qualification_summary=summarize_futu_k1m_closure_qualification(
            closure_qualification
        )
        bar_closure_evidence_state=derive_futu_k1m_bar_closure_state(
            currentness_summary=currentness_summary,
            closure_qualification_summary=closure_qualification_summary,
        )
        canonical_export_updated=False
        should_export=(
            consumer_result.bars_ingested > 0
            or not os.path.exists(canonical_snapshot_path)
            or market_state != last_export_market_state
            or bar_closure_evidence_state != last_export_bar_closure
            or delivery_mode_evidence_state != last_export_delivery_mode
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
                    delivery_mode=delivery_mode_evidence_state,
                    bar_closure=bar_closure_evidence_state,
                )
                write_canonical_snapshot_export(canonical_snapshot_path,canonical_export)
                canonical_export_sequence=next_export_sequence
                canonical_export_status="PASS"
                canonical_export_error=None
                canonical_export_last_write_utc=now.isoformat()
                last_export_market_state=market_state
                last_export_bar_closure=bar_closure_evidence_state
                last_export_delivery_mode=delivery_mode_evidence_state
                canonical_export_updated=True
            except Exception as exc:
                canonical_export_status="BLOCKED"
                canonical_export_error=type(exc).__name__
        bar_closure_state=(
            "PROVEN"
            if (
                bar_closure_evidence_state == "PROVEN"
                and canonical_export_status == "PASS"
                and last_export_bar_closure == "PROVEN"
            )
            else "UNPROVEN"
        )
        delivery_mode_state=(
            "REALTIME"
            if (
                delivery_mode_evidence_state == "REALTIME"
                and canonical_export_status == "PASS"
                and last_export_delivery_mode == "REALTIME"
            )
            else "UNKNOWN"
        )
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
          "k1m_closure_qualification":closure_qualification_payload,
          "k1m_closure_qualification_summary":closure_qualification_summary,
          "bar_closure_evidence_state":bar_closure_evidence_state,
          "quote_right_evidence":quote_right_payload,
          "research_consumer":consumer_payload,
          "historical_warm_start":{
            "status":warm_start_status,
            "symbols":warm_start_payload,
            "seeded_symbol_count":warm_start_pass_count,
            "total_bars_ingested":warm_start_total_seeded,
            "research_only":True,
            "realtime_currentness_proven":False,
            "bar_closure_promotion_authorized":False,
            "radar_admission":"BLOCKED",
            "live_trade":False,
          },
          "canonical_cache":canonical_cache,
          "canonical_snapshot_export":{
              "status":canonical_export_status,
              "error":canonical_export_error,
              "schema":CANONICAL_SNAPSHOT_SCHEMA,
              "path":canonical_snapshot_path,
              "sequence":canonical_export_sequence,
              "updated":canonical_export_updated,
              "last_write_utc":canonical_export_last_write_utc,
              "delivery_mode":last_export_delivery_mode or "UNKNOWN",
              "bar_closure":last_export_bar_closure or "UNPROVEN",
              "repo_sha":repo_sha,
          },
          "adapter_diagnostics":adapter.diagnostics(),
          "delivery_mode":delivery_mode_state,"bar_closure":bar_closure_state,
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
