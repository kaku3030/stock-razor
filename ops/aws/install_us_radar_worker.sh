#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-us-radar}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-us-radar.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact worker commit SHA is required}"
SOURCE_REPO_SHA="${SOURCE_REPO_SHA:?SOURCE_REPO_SHA exact acquisition commit SHA is required}"
SOURCE_PATH="${SOURCE_PATH:-/run/stock-razor-us-livefeed/canonical-market-snapshot.json}"
STATUS_PATH="${STATUS_PATH:-/run/stock-razor-us-radar/latest-research-state.json}"
OPTIONS_CONTEXT_ENABLED="${OPTIONS_CONTEXT_ENABLED:-false}"
OPTIONS_CONTEXT_PATH="${OPTIONS_CONTEXT_PATH:-/run/stock-razor-us-options-intelligence/options-intelligence.json}"
OPTIONS_SOURCE_REPO_SHA="${OPTIONS_SOURCE_REPO_SHA:-}"

case "$REPO_REF" in
  (*[!0-9a-f]*|"") echo "REPO_REF must be lowercase hex" >&2; exit 2;;
esac
case "$SOURCE_REPO_SHA" in
  (*[!0-9a-f]*|"") echo "SOURCE_REPO_SHA must be lowercase hex" >&2; exit 2;;
esac
test "${#REPO_REF}" -eq 40
test "${#SOURCE_REPO_SHA}" -eq 40
case "$OPTIONS_CONTEXT_ENABLED" in
  (true|false) ;;
  (*) echo "OPTIONS_CONTEXT_ENABLED must be true or false" >&2; exit 2;;
esac
if [ "$OPTIONS_CONTEXT_ENABLED" = "true" ]; then
  case "$OPTIONS_SOURCE_REPO_SHA" in
    (*[!0-9a-f]*|"") echo "OPTIONS_SOURCE_REPO_SHA exact options source SHA is required when enabled" >&2; exit 2;;
  esac
  test "${#OPTIONS_SOURCE_REPO_SHA}" -eq 40
fi
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
"$INSTALL_ROOT/venv/bin/pip" install --disable-pip-version-check --no-input \
  'numpy==1.26.4' 'pandas==2.2.2' 'PyYAML==6.0.2'

PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<'PY'
from src.services.stock_radar_v2.canonical_snapshot_worker import (
    CanonicalSnapshotRadarEvaluator,
    CanonicalSnapshotRadarWorker,
)
from src.services.stock_radar_v2.daily_history_reader import (
    load_futu_us_daily_history_frames,
)
from src.services.stock_radar_v2.technical_state import StockRadarTechnicalStateService
from src.services.stock_radar_v2.daily_history_reader import load_futu_us_daily_history_frames
from src.services.stock_radar_v2.options_context_reader import RadarOptionsContextReader
print("US_RADAR_WORKER_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

from src.services.stock_radar_v2.canonical_snapshot_worker import (
    CanonicalSnapshotRadarEvaluator,
    CanonicalSnapshotRadarWorker,
)
from src.services.stock_radar_v2.daily_history_reader import (
    load_futu_us_daily_history_frames,
)
from src.services.stock_radar_v2.options_context_reader import RadarOptionsContextReader

worker_repo_sha = os.environ["STOCK_RAZOR_WORKER_REPO_SHA"].strip().lower()
expected_source_repo_sha = os.environ["STOCK_RAZOR_SOURCE_REPO_SHA"].strip().lower()
source_path = os.environ.get(
    "STOCK_RAZOR_CANONICAL_SNAPSHOT_PATH",
    "/run/stock-razor-us-livefeed/canonical-market-snapshot.json",
)
daily_history_path = os.environ.get(
    "STOCK_RAZOR_US_DAILY_HISTORY_PATH",
    "/run/stock-razor-us-livefeed/daily-history.json",
)
status_path = os.environ.get(
    "STOCK_RAZOR_US_RADAR_STATUS_PATH",
    "/run/stock-razor-us-radar/latest-research-state.json",
)
poll_seconds = max(1.0, float(os.environ.get("STOCK_RAZOR_US_RADAR_POLL_SECONDS", "5")))
options_context_enabled = os.environ.get("STOCK_RAZOR_OPTIONS_CONTEXT_ENABLED", "false").strip().lower() == "true"
options_context_path = os.environ.get(
    "STOCK_RAZOR_OPTIONS_CONTEXT_PATH",
    "/run/stock-razor-us-options-intelligence/options-intelligence.json",
)
options_source_repo_sha = os.environ.get("STOCK_RAZOR_OPTIONS_SOURCE_REPO_SHA", "").strip().lower() or None
runtime_id = os.environ.get("STOCK_RAZOR_RUNTIME_ID") or str(uuid.uuid4())
host_id = socket.gethostname()

evaluator = CanonicalSnapshotRadarEvaluator(max_active_age_seconds=120)
options_reader = RadarOptionsContextReader(max_age_seconds=120)
worker = CanonicalSnapshotRadarWorker(
    expected_repo_sha=expected_source_repo_sha,
    evaluator=evaluator,
)
cycle = 0


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
    now = datetime.now(timezone.utc)
    daily_frames, daily_history = load_futu_us_daily_history_frames(
        daily_history_path,
        expected_repo_sha=expected_source_repo_sha,
    )
    options_result = None
    options_contexts = {}
    if options_context_enabled:
        options_result = options_reader.read_file(
            options_context_path,
            expected_repo_sha=options_source_repo_sha,
        )
        if options_result.status == "PASS":
            options_contexts = options_result.by_symbol()

    analysis_started = time.perf_counter()
    evaluation = worker.poll_file(
        source_path,
        daily_frames=daily_frames,
        options_contexts=options_contexts,
    )
    poll_elapsed_ms = round((time.perf_counter() - analysis_started) * 1000, 3)
    radar_analysis_performed = evaluation.status == "PASS"
    radar_analysis_latency_ms = poll_elapsed_ms if radar_analysis_performed else None
    completed_at = datetime.now(timezone.utc)
    data_to_radar_latency_ms = None
    if radar_analysis_performed and evaluation.source_emitted_at is not None:
        source_emitted = evaluation.source_emitted_at.astimezone(timezone.utc)
        data_to_radar_latency_ms = round(
            max(0.0, (completed_at - source_emitted).total_seconds()) * 1000,
            3,
        )
    evaluation_payload = evaluation.to_dict()
    cycle += 1
    payload = {
        "type": "us_radar_research_heartbeat",
        "runtime_instance_id": runtime_id,
        "worker_repo_sha": worker_repo_sha,
        "expected_source_repo_sha": expected_source_repo_sha,
        "host_id": host_id,
        "sequence": cycle,
        "emitted_at_utc": completed_at.isoformat(),
        "source_path": source_path,
        "daily_history_path": daily_history_path,
        "daily_history": daily_history,
        "options_context": {
            "enabled": options_context_enabled,
            "source_path": options_context_path if options_context_enabled else None,
            "expected_source_repo_sha": options_source_repo_sha if options_context_enabled else None,
            "read": options_result.to_dict() if options_result is not None else None,
        },
        "poll_status": evaluation.status,
        "radar_analysis_performed": radar_analysis_performed,
        "radar_analysis_latency_ms": radar_analysis_latency_ms,
        "data_to_radar_latency_ms": data_to_radar_latency_ms,
        "evaluation": evaluation_payload,
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
Description=STOCK RAZOR canonical-snapshot US Radar research worker
After=stock-razor-us-livefeed.service
Wants=stock-razor-us-livefeed.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$INSTALL_ROOT/repo
Environment=STOCK_RAZOR_WORKER_REPO_SHA=$REPO_REF
Environment=STOCK_RAZOR_SOURCE_REPO_SHA=$SOURCE_REPO_SHA
Environment=STOCK_RAZOR_CANONICAL_SNAPSHOT_PATH=$SOURCE_PATH
Environment=STOCK_RAZOR_US_DAILY_HISTORY_PATH=/run/stock-razor-us-livefeed/daily-history.json
Environment=STOCK_RAZOR_US_RADAR_STATUS_PATH=$STATUS_PATH
Environment=STOCK_RAZOR_US_RADAR_POLL_SECONDS=5
Environment=STOCK_RAZOR_OPTIONS_CONTEXT_ENABLED=$OPTIONS_CONTEXT_ENABLED
Environment=STOCK_RAZOR_OPTIONS_CONTEXT_PATH=$OPTIONS_CONTEXT_PATH
Environment=STOCK_RAZOR_OPTIONS_SOURCE_REPO_SHA=$OPTIONS_SOURCE_REPO_SHA
RuntimeDirectory=stock-razor-us-radar
RuntimeDirectoryMode=0755
ExecStart=$INSTALL_ROOT/venv/bin/python $INSTALL_ROOT/run.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
PrivateNetwork=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/run/stock-razor-us-livefeed
ReadOnlyPaths=-/run/stock-razor-us-options-intelligence

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
