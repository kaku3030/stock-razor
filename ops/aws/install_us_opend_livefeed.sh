#!/usr/bin/env bash
set -euo pipefail
INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-us-livefeed}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-us-livefeed.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"
OPEND_CLIENT_ROOT="${OPEND_CLIENT_ROOT:-/opt/stock-razor-opend-client}"

test "$(id -u)" -eq 0
test -x "$OPEND_CLIENT_ROOT/venv/bin/python"
# Independent EC2-side market-hours gate BEFORE git fetch, in-place repo
# checkout, daemon reload, or service restart. The workflow check alone can
# race with the session boundary. Fail closed if time/zone cannot be read.
require_safe_us_restart_window() {
"$OPEND_CLIENT_ROOT/venv/bin/python" - <<'PY_RESTART_WINDOW'
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
try:
    local = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    if local.weekday() < 5 and time(9, 0) <= local.time() < time(16, 30):
        print("US_LIVEFEED_RESTART_TIME=US_SESSION_SAFETY_WINDOW_BLOCKED")
        raise SystemExit(2)
except SystemExit:
    raise
except Exception:
    print("US_LIVEFEED_RESTART_TIME=CLOCK_UNKNOWN_BLOCKED")
    raise SystemExit(2)
print("US_LIVEFEED_RESTART_TIME=SAFE_OFF_WINDOW")
PY_RESTART_WINDOW
}
require_safe_us_restart_window
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
from src.services.live_feed.opend_readonly_candidate_plan import plan_readonly_subscriptions
from src.services.live_feed.controller import LiveFeedController
from src.services.live_feed.canonical_snapshot_export import build_canonical_snapshot_export
from src.services.live_feed.futu_k1m_closure_pipeline import FutuK1MClosurePipeline
from src.services.live_feed.us_intraday_closure import qualify_us_current_session_intraday_closure
from src.services.live_feed.us_postclose_terminal_reconciliation import reconcile_us_postclose_terminal_minutes, postclose_history_retry_due
from src.services.live_feed.futu_k1m_research_consumer import FutuK1MResearchConsumer
from src.services.live_feed.futu_k1m_warm_start_runtime import seed_futu_k1m_research_cache
from src.services.live_feed.futu_us_daily_history import (
    build_futu_us_daily_history,
    write_futu_us_daily_history,
)
from src.services.live_feed.futu_quote_right import classify_futu_us_quote_right
from src.services.realtime_market_data import RealtimeMarketDataService
print("US_LIVEFEED_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json, os, socket, threading, time, uuid
from datetime import datetime, timezone
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
from src.services.live_feed.us_intraday_closure import qualify_us_current_session_intraday_closure
from src.services.live_feed.us_postclose_terminal_reconciliation import reconcile_us_postclose_terminal_minutes, postclose_history_retry_due
from src.services.live_feed.futu_k1m_currentness import (
    classify_futu_us_k1m_currentness,
    futu_us_market_state_to_session,
    summarize_futu_k1m_currentness,
)
from src.services.live_feed.futu_k1m_research_consumer import FutuK1MResearchConsumer
from src.services.live_feed.futu_k1m_warm_start_runtime import seed_futu_k1m_research_cache
from src.services.live_feed.futu_us_daily_history import (
    build_futu_us_daily_history,
    daily_history_refresh_due,
    write_futu_us_daily_history,
)
from src.services.live_feed.futu_quote_right import classify_futu_us_quote_right
from src.services.live_feed.runtime_bridge import LiveFeedRuntimeBridge
from src.services.live_feed.opend_readonly_candidate_plan import plan_readonly_subscriptions
from src.services.live_feed.producer_wakeup import DataArrivalWake
from src.services.realtime_market_data import RealtimeMarketDataService

CODES=("US.AMD","US.NVDA","US.TSLA","US.AAPL","US.QQQ","US.GLDM","US.LITE","US.AAOI","US.CIEN","US.SCHD","US.KMLM","US.GLD","US.DBMF","US.BTAL")
runtime_id=os.environ.get("STOCK_RAZOR_RUNTIME_ID") or str(uuid.uuid4())
repo_sha=os.environ["STOCK_RAZOR_REPO_SHA"]
status_path=os.environ.get("STOCK_RAZOR_US_LIVEFEED_STATUS_PATH","/run/stock-razor-us-livefeed/latest-heartbeat.json")
canonical_snapshot_path=os.environ.get(
    "STOCK_RAZOR_CANONICAL_SNAPSHOT_PATH",
    "/run/stock-razor-us-livefeed/canonical-market-snapshot.json",
)
daily_history_path=os.environ.get(
    "STOCK_RAZOR_US_DAILY_HISTORY_PATH",
    "/run/stock-razor-us-livefeed/daily-history.json",
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
    max_minutes=1600,
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
data_wakeup=DataArrivalWake()
def read_data_event_count():
    with evidence_lock:
        return data_event_count
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
            # Callback never drains or opens a new provider request.
            data_wakeup.notify()
bridge=LiveFeedRuntimeBridge(controller,adapter,on_event_accepted=on_event_accepted)
streams=[SemanticStreamKey("futu","us",c,"K_1M","1m") for c in CODES]
bridge.start(streams)
# Candidate changes are OBSERVED ONLY. Never add a provider call here.
preview_csv=os.environ.get("STOCK_RAZOR_OPEND_PREVIEW_CANDIDATES")
if preview_csv is None:
    preview_desired=tuple(streams)
elif len(preview_csv)>4096:
    preview_desired=None
else:
    preview_desired=tuple(
        SemanticStreamKey("futu","us",code,"K_1M","1m")
        for code in preview_csv.split(",")
    )
def fetch_history_page(symbol,start_date,end_date,page_req_key):
    ret,data,next_page_req_key=ctx.request_history_kline(
        symbol,
        start=start_date,
        end=end_date,
        ktype=ft.KLType.K_1M,
        autype=ft.AuType.NONE,
        max_count=1000,
        page_req_key=page_req_key,
        extended_time=False,
        session=ft.Session.RTH,
    )
    if ret != ft.RET_OK:
        raise RuntimeError("FUTU_HISTORY_QUERY_FAILED")
    if not hasattr(data,"to_dict"):
        raise RuntimeError("FUTU_HISTORY_QUERY_INVALID_PAYLOAD")
    return tuple(data.to_dict("records")),next_page_req_key
warm_start_seeded_total=0
try:
    warm_start_result=seed_futu_k1m_research_cache(
        CODES,
        fetch_page=fetch_history_page,
        market_data=market_data,
        received_at=datetime.now(timezone.utc),
        lookback_days=10,
        max_pages=5,
        required_sessions=3,
    )
    warm_start_payload=warm_start_result.to_dict()
    warm_start_seeded_total=warm_start_result.seeded_total
except Exception as exc:
    warm_start_payload={
        "status":"BLOCKED",
        "error":"WARM_START_EXCEPTION:"+type(exc).__name__,
        "symbols":{},
        "seeded_total":0,
        "unchanged_total":0,
        "lookback_days":10,
        "max_pages":5,
        "required_sessions":3,
        "purpose":"RESEARCH_CACHE_WARM_START",
        "historical_query":True,
        "realtime_currentness_proven":False,
        "bar_closure_promotion_authorized":False,
        "radar_admission":"BLOCKED",
        "live_trade":False,
    }

def fetch_daily_rows(symbol,start_date,end_date):
    ret,data,_=ctx.request_history_kline(
        symbol,
        start=start_date,
        end=end_date,
        ktype=ft.KLType.K_DAY,
        autype=ft.AuType.NONE,
        max_count=1000,
    )
    if ret != ft.RET_OK:
        raise RuntimeError("FUTU_DAILY_HISTORY_QUERY_FAILED")
    if not hasattr(data,"to_dict"):
        raise RuntimeError("FUTU_DAILY_HISTORY_INVALID_PAYLOAD")
    return tuple(data.to_dict("records"))

daily_observed_at=datetime.now(timezone.utc)
try:
    daily_history_payload=build_futu_us_daily_history(
        CODES,
        fetch_rows=fetch_daily_rows,
        repo_sha=repo_sha,
        runtime_instance_id=runtime_id,
        observed_at_utc=daily_observed_at,
        required_rows=120,
        lookback_calendar_days=260,
    )
    write_futu_us_daily_history(daily_history_path,daily_history_payload)
except Exception as exc:
    daily_history_payload={
        "schema":"stock_razor_futu_us_daily_history_v1",
        "repo_sha":repo_sha,
        "runtime_instance_id":runtime_id,
        "emitted_at_utc":daily_observed_at.isoformat(),
        "status":"BLOCKED",
        "error":"DAILY_HISTORY_EXCEPTION:"+type(exc).__name__,
        "symbols":{},
        "required_rows":120,
        "lookback_calendar_days":260,
        "provider":"futu",
        "feed":"opend",
        "same_opend_context_required":True,
        "historical_query":True,
        "currentness_proven":False,
        "bar_closure_promotion_authorized":False,
        "research_only":True,
        "can_confirm_signal":False,
        "radar_admission":"BLOCKED",
        "live_trade":False,
    }
    try:
        write_futu_us_daily_history(daily_history_path,daily_history_payload)
    except Exception:
        pass

daily_history_summary={
    "status":daily_history_payload.get("status"),
    "path":daily_history_path,
    "required_rows":daily_history_payload.get("required_rows"),
    "symbols":{
        code:{
            "status":(daily_history_payload.get("symbols") or {}).get(code,{}).get("status"),
            "row_count":int((daily_history_payload.get("symbols") or {}).get(code,{}).get("row_count") or 0),
            "latest_date":(daily_history_payload.get("symbols") or {}).get(code,{}).get("latest_date"),
        }
        for code in CODES
    },
    "same_opend_context_required":True,
    "historical_query":True,
    "currentness_proven":False,
    "bar_closure_promotion_authorized":False,
    "radar_admission":"BLOCKED",
    "live_trade":False,
}
daily_history_last_attempt_utc=(
    daily_observed_at
    if daily_history_refresh_due(daily_observed_at, None)
    else None
)
daily_history_summary["last_refresh_attempt_utc"]=daily_observed_at.isoformat()
daily_history_summary["last_refresh_status"]=daily_history_payload.get("status")

def maybe_refresh_daily_history(now_utc):
    global daily_history_payload,daily_history_summary,daily_history_last_attempt_utc
    if not daily_history_refresh_due(now_utc,daily_history_last_attempt_utc):
        return
    # One bounded refresh per New York weekday, after 01:00 ET. This runs
    # before the US premarket stream begins and does not add a connection.
    daily_history_last_attempt_utc=now_utc
    try:
        refreshed=build_futu_us_daily_history(
            CODES,
            fetch_rows=fetch_daily_rows,
            repo_sha=repo_sha,
            runtime_instance_id=runtime_id,
            observed_at_utc=now_utc,
            required_rows=120,
            lookback_calendar_days=260,
        )
        write_futu_us_daily_history(daily_history_path,refreshed)
    except Exception as exc:
        refreshed={
            "schema":"stock_razor_futu_us_daily_history_v1",
            "repo_sha":repo_sha,
            "runtime_instance_id":runtime_id,
            "emitted_at_utc":now_utc.isoformat(),
            "status":"BLOCKED",
            "error":"DAILY_HISTORY_REFRESH_EXCEPTION:"+type(exc).__name__,
            "symbols":{},
            "required_rows":120,
            "lookback_calendar_days":260,
            "provider":"futu",
            "feed":"opend",
            "same_opend_context_required":True,
            "historical_query":True,
            "currentness_proven":False,
            "bar_closure_promotion_authorized":False,
            "research_only":True,
            "can_confirm_signal":False,
            "radar_admission":"BLOCKED",
            "live_trade":False,
        }
        try:
            write_futu_us_daily_history(daily_history_path,refreshed)
        except Exception:
            pass
    daily_history_payload=refreshed
    daily_history_summary={
        "status":refreshed.get("status"),
        "path":daily_history_path,
        "required_rows":refreshed.get("required_rows"),
        "symbols":{
            code:{
                "status":(refreshed.get("symbols") or {}).get(code,{}).get("status"),
                "row_count":int((refreshed.get("symbols") or {}).get(code,{}).get("row_count") or 0),
                "latest_date":(refreshed.get("symbols") or {}).get(code,{}).get("latest_date"),
            }
            for code in CODES
        },
        "same_opend_context_required":True,
        "historical_query":True,
        "currentness_proven":False,
        "bar_closure_promotion_authorized":False,
        "radar_admission":"BLOCKED",
        "live_trade":False,
        "last_refresh_attempt_utc":now_utc.isoformat(),
        "last_refresh_status":refreshed.get("status"),
    }
seq=0
# Maximum two same-day RTH historical attempts after 16:30 ET,
# with at least 30 minutes between failed attempts; never realtime admission.
postclose_attempt_count=0
postclose_last_attempt_at=None
postclose_reconciliation={
    "session_date":None,
    "status":"NOT_DUE","reason":"WAITING_FOR_POSTCLOSE_FULL_GRID",
    "provider_requests":0,"seeded_count":0,
    "historical_query":True,"currentness_proven":False,
    "bar_closure_promotion_authorized":False,
    "radar_admission":"BLOCKED","live_trade":False,
}
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
# Callback-driven wakeup of the existing one-writer consumer. No additional
# Futu RPC or subscriptions; periodic market-state fallback remains 5s.
producer_event_min_interval_seconds=0.10
market_state_query_interval_seconds=5.0
last_market_state_query_monotonic=None
last_consumed_data_event_count=-1
consumer_backlog_pending=False
market_state="UNKNOWN"
state_ret=-1
idle_fastpath_skips=0
last_consumer_dispatch_monotonic=None
def publish(payload):
    os.makedirs(os.path.dirname(status_path),exist_ok=True)
    tmp=status_path+".tmp"
    with open(tmp,"w",encoding="utf-8") as h:
        json.dump(payload,h,separators=(",",":")); h.flush(); os.fsync(h.fileno())
    os.replace(tmp,status_path)
try:
    while True:
        maybe_refresh_daily_history(datetime.now(timezone.utc))
        monotonic_now=time.monotonic()
        until_state_query=(
            0.0 if last_market_state_query_monotonic is None
            else max(0.0, market_state_query_interval_seconds
                     - (monotonic_now-last_market_state_query_monotonic))
        )
        if not consumer_backlog_pending:
            # Atomic clear + second counter check avoids a missed callback
            # between the first observation and wait. Health queries run on
            # their own bounded deadline even when no callbacks arrive.
            data_wakeup.wait_when_unchanged(
                read_data_event_count,
                last_processed_count=last_consumed_data_event_count,
                max_wait_seconds=until_state_query,
            )
        monotonic_now=time.monotonic()
        pending_data_event_count=read_data_event_count()
        state_due=(
            last_market_state_query_monotonic is None
            or monotonic_now-last_market_state_query_monotonic >= market_state_query_interval_seconds
        )
        event_due=(
            pending_data_event_count != last_consumed_data_event_count
            or consumer_backlog_pending
        )
        if not state_due and not event_due:
            idle_fastpath_skips+=1
            continue
        if event_due and not state_due and last_consumer_dispatch_monotonic is not None:
            elapsed=monotonic_now-last_consumer_dispatch_monotonic
            if elapsed < producer_event_min_interval_seconds:
                # Coalesce callback bursts into a single bounded 100ms pass.
                time.sleep(producer_event_min_interval_seconds-elapsed)
                monotonic_now=time.monotonic()
                state_due=(
                    last_market_state_query_monotonic is None
                    or monotonic_now-last_market_state_query_monotonic >= market_state_query_interval_seconds
                )
        if state_due:
            # No additional global-state RPCs; never infer PASS when it fails.
            last_market_state_query_monotonic=monotonic_now
            try:
                state_ret,state_data=ctx.get_global_state()
                market_state=(str(state_data.get("market_us") or "UNKNOWN")
                              if state_ret==ft.RET_OK and isinstance(state_data,dict) else "UNKNOWN")
            except Exception:
                state_ret=-1
                market_state="UNKNOWN"
        market_state_us=market_state
        cache_session=futu_us_market_state_to_session(market_state)
        snap=bridge.drain()
        consumer_result=research_consumer.run_once(max_events=1000)
        last_consumer_dispatch_monotonic=time.monotonic()
        last_consumed_data_event_count=pending_data_event_count
        # Bounded catch-up: keep draining after a full 1000-evidence batch.
        consumer_backlog_pending=(consumer_result.evidence_processed >= 1000)
        if (
            not state_due
            and consumer_result.bars_ingested == 0
            and consumer_result.stopped_reason is None
        ):
            # Forming K1M updates are not a qualified closed bar. Avoid
            # heavyweight canonical reconstruction and noisy heartbeat logs.
            continue
        seq+=1; now=datetime.now(timezone.utc)
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
        postclose_seeded_this_pass=0
        local_now=now.astimezone(ZoneInfo("America/New_York"))
        local_day=local_now.date().isoformat()
        if postclose_reconciliation.get("session_date") != local_day:
            # Never carry yesterday's PASS_HISTORICAL_ONLY report forward
            # as if it applied to today's NY exchange date.
            postclose_reconciliation={
                "session_date":local_day,
                "status":"NOT_DUE","reason":"WAITING_FOR_POSTCLOSE_FULL_GRID",
                "provider_requests":0,"seeded_count":0,
                "historical_query":True,"currentness_proven":False,
                "bar_closure_promotion_authorized":False,
                "radar_admission":"BLOCKED","live_trade":False,
            }
            postclose_attempt_count=0
            postclose_last_attempt_at=None
        if (
            postclose_history_retry_due(
                attempts=postclose_attempt_count,
                last_attempt_at=postclose_last_attempt_at,
                observed_at=now,
                prior_status=postclose_reconciliation.get("status"),
            )
            and (local_now.hour,local_now.minute) >= (16,30)
            and market_state in ("AFTER_HOURS_BEGIN","AFTER_HOURS_END","OVERNIGHT","CLOSED","WAITING_OPEN")
            and any(
                isinstance(label,str)
                and label >= local_day+" 15:59:00"
                and label.startswith(local_day+" ")
                for label in time_keys.values()
            )
        ):
            # The existing RTH history fetch is already bound to the same
            # OpenD context and explicitly excludes extended-hour candles.
            postclose_attempt_count+=1
            postclose_last_attempt_at=now
            postclose_reconciliation=reconcile_us_postclose_terminal_minutes(
                CODES,
                fetch_page=fetch_history_page,
                market_data=market_data,
                latest_time_keys=time_keys,
                observed_at=now,
                market_state=market_state,
            )
            postclose_seeded_this_pass=int(postclose_reconciliation["seeded_count"])
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
        intraday_closure={
            code:qualify_us_current_session_intraday_closure(
                {"15m":canonical_snapshots[code].bars_15m,
                 "1h":canonical_snapshots[code].bars_1h},
                as_of=now,
            )
            for code in CODES
        }
        intraday_closure_summary=(
            "PASS" if intraday_closure and all(item.get("status") == "PASS" for item in intraday_closure.values())
            else "UNKNOWN"
        )
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
        if intraday_closure_summary != "PASS":
            bar_closure_evidence_state="UNPROVEN"
        canonical_export_updated=False
        should_export=(
            consumer_result.bars_ingested > 0
            or postclose_seeded_this_pass > 0
            or (warm_start_seeded_total > 0 and canonical_export_sequence == 0)
            or not os.path.exists(canonical_snapshot_path)
            or market_state != last_export_market_state
            or bar_closure_evidence_state != last_export_bar_closure
            or delivery_mode_evidence_state != last_export_delivery_mode
            or canonical_export_status != "PASS"
            # Keep the canonical file's publication sequence moving with the
            # runtime heartbeat. The reader separately evaluates the newest
            # provider bar timestamp, so this cannot turn stale bars into
            # fresh data.
            or state_due
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
        try:
            if preview_desired is None:
                candidate_preview={"status":"BLOCKED","reason":"PREVIEW_INPUT_TOO_LONG",
                    "provider_calls":0,"subscription_changes":0,
                    "radar_admission":"BLOCKED","source_arbiter_admission":"BLOCKED",
                    "paper_auto_ready":False,"live_trade":False}
            else:
                result=plan_readonly_subscriptions(
                    snap.subscribed,preview_desired,quota=None,now_utc=now,
                    protected=tuple(streams),
                )
                candidate_preview={
                    "status":result.status,"reason":result.reason,
                    "acknowledged_count":len(result.currently_acknowledged),
                    "proposed_additions":list(result.proposed_additions),
                    "proposed_removals":list(result.proposed_removals),
                    "evidence_scope":result.evidence_scope,
                    "provider_calls":result.provider_calls,
                    "subscription_changes":result.subscription_changes,
                    "radar_admission":result.radar_admission,
                    "source_arbiter_admission":result.source_arbiter_admission,
                    "paper_auto_ready":result.paper_auto_ready,
                    "live_trade":result.live_trade,
                }
        except Exception:
            candidate_preview={"status":"BLOCKED","reason":"OBSERVER_EXCEPTION",
                "provider_calls":0,"subscription_changes":0,
                "radar_admission":"BLOCKED","source_arbiter_admission":"BLOCKED",
                "paper_auto_ready":False,"live_trade":False}
        heartbeat={"type":"us_opend_livefeed_heartbeat","runtime_instance_id":runtime_id,
          "repo_sha":repo_sha,"host_id":host_id,"sequence":seq,"emitted_at_utc":now.isoformat(),
          "symbols":list(CODES),"subscribed":[k.symbol for k in snap.subscribed],
          "dynamic_subscription_preview":candidate_preview,
          "controller_lifecycle":snap.controller.lifecycle_state.value,
          "controller_failure_class":snap.controller.failure_class.value,
          "controller_findings_tail":list(snap.controller.findings[-20:]),
          "event_count":data_count,"accepted_event_count":accepted_count,
          "last_push_utc":push_utc,"market_state_us":market_state,
          "cache_session_us":cache_session,
          "producer_loop_observation":{
              "wakeup_mode":"CALLBACK_EVENT_WITH_PERIODIC_HEALTH_DEADLINE",
              "event_min_interval_seconds":producer_event_min_interval_seconds,
              "market_state_query_interval_seconds":market_state_query_interval_seconds,
              "idle_fastpath_skips":idle_fastpath_skips,
              "last_seen_data_event_count":last_consumed_data_event_count,
              "consumer_backlog_pending":consumer_backlog_pending,
              "measurement_scope":"EVENT_AWARE_PRODUCER_LOOP_NOT_E2E_SLO",
          },
          "market_state_evidence":"PASS" if state_ret==ft.RET_OK else "BLOCKED",
          "latest_k1m_time_keys":time_keys,"k1m_currentness":currentness_payload,
          "k1m_currentness_summary":currentness_summary,
          "closure_pipeline":closure_diagnostics,
          "k1m_closure_qualification":closure_qualification_payload,
          "k1m_closure_qualification_summary":closure_qualification_summary,
          "intraday_closure_15m_60m":intraday_closure,
          "intraday_closure_15m_60m_summary":intraday_closure_summary,
          "bar_closure_evidence_state":bar_closure_evidence_state,
          "quote_right_evidence":quote_right_payload,
          "research_consumer":consumer_payload,
          "warm_start":warm_start_payload,
          "postclose_reconciliation":postclose_reconciliation,
          "daily_history":daily_history_summary,
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
          "research_only":True,"can_confirm_signal":False,
          "radar_admission":"BLOCKED","live_trade":False}
        publish(heartbeat); print(json.dumps(heartbeat,separators=(",",":")),flush=True)
        # An RTH K_1M feed can legitimately have no callback off-session.
        # Only a POSITIVELY OBSERVED regular session may trigger startup
        # callback-starvation restart; unknown state never proves readiness.
        if (
            data_event_count == 0
            and state_ret == ft.RET_OK
            and cache_session == "regular"
            and (time.monotonic()-startup_monotonic) >= startup_callback_deadline_seconds
        ):
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
# Recheck immediately before actual restart, including unexpectedly slow
# downloads/builds that cross the conservative market-hours boundary.
require_safe_us_restart_window
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
