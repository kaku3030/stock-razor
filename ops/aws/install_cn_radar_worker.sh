#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/stock-razor-cn-radar}"
SERVICE_NAME="${SERVICE_NAME:-stock-razor-cn-radar.service}"
REPO_URL="${REPO_URL:-https://github.com/kaku3030/stock-razor.git}"
REPO_REF="${REPO_REF:?REPO_REF exact worker commit SHA is required}"
SOURCE_PROVIDER="${SOURCE_PROVIDER:-eastmoney}"
case "$SOURCE_PROVIDER" in
  eastmoney)
    SOURCE_PATH=/run/stock-razor-cn-eastmoney/latest-observation.json
    SOURCE_SERVICE=stock-razor-cn-eastmoney.service ;;
  tickflow)
    SOURCE_PATH=/run/stock-razor-cn-tickflow/latest-research-observation.json
    SOURCE_SERVICE=stock-razor-cn-tickflow-research.service ;;
  *) echo CN_RADAR_SOURCE_PROVIDER_INVALID >&2; exit 2 ;;
esac
STATUS_PATH="${STATUS_PATH:-/run/stock-razor-cn-radar/latest-research-state.json}"
POLL_SECONDS="${POLL_SECONDS:-5}"

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
"$INSTALL_ROOT/venv/bin/pip" install --disable-pip-version-check --no-input   'numpy==1.26.4' 'pandas==2.2.2' 'PyYAML==6.0.2'

PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<'PY'
from src.services.stock_radar_v2.cn_observation_analysis import (
    CN_RADAR_SCHEMA,
    evaluate_cn_observation_payload,
)
assert CN_RADAR_SCHEMA == "stock_razor_cn_radar_research_v1"
assert callable(evaluate_cn_observation_payload)
print("CN_RADAR_IMPORT_SMOKE=PASS")
PY

cat >"$INSTALL_ROOT/run.py" <<'PY'
import json
import os
import socket
import time
import uuid

from data_provider.cn_tickflow_research_cache import MAX_BYTES
from src.services.stock_radar_v2.tickflow_observation_analysis import (
    evaluate_tickflow_observation_payload, validate_tickflow_source_clock,
)
from datetime import datetime, timezone

from src.services.stock_radar_v2.cn_observation_analysis import (
    evaluate_cn_observation_payload,
)

source_provider = os.environ.get("STOCK_RAZOR_CN_RADAR_SOURCE_PROVIDER", "eastmoney")
worker_repo_sha = os.environ["STOCK_RAZOR_WORKER_REPO_SHA"].strip().lower()
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
cycle = 0
last_key = None
last_evaluation = None


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
    cycle += 1
    poll_status = "BLOCKED"
    reasons = []
    evaluation = None
    source_repo_sha = None
    source_runtime_instance_id = None
    source_sequence = None
    source_emitted_at_utc = None
    source_emitted = None
    source_age_seconds = None
    radar_analysis_performed = False
    radar_analysis_latency_ms = None
    data_to_radar_latency_ms = None
    # Accept a validated raw source independently from strategy promotion.
    source_acceptance_status = "NOT_READ"
    analysis_status = "NOT_RUN"
    bar_state = "UNKNOWN"
    strategy_admission = "BLOCKED"

    try:
        with open(source_path, "rb") as handle:
            text = handle.read(MAX_BYTES + 1)
            if len(text) > MAX_BYTES:
                raise ValueError("observation too large")
            source = json.loads(text)
            source_stat = os.fstat(handle.fileno())
        if not isinstance(source, dict):
            raise ValueError("source root must be object")

        source_repo_sha = source.get("repo_sha")
        source_runtime_instance_id = source.get("runtime_instance_id") or "NOT_VERIFIED"
        source_sequence = int(source.get("sequence") or 0)
        source_emitted_at_utc = source.get("observed_at_utc" if source_provider == "tickflow" else "emitted_at_utc")
        source_emitted = datetime.fromisoformat(str(source_emitted_at_utc))
        if source_emitted.tzinfo is None or source_emitted.utcoffset() is None:
            raise ValueError("source emitted_at must be timezone-aware")
        source_age_delta_seconds = (
            now - source_emitted.astimezone(timezone.utc)
        ).total_seconds()
        if source_age_delta_seconds < 0:
            # Future-dated source clocks are invalid; never clamp them to a
            # plausible zero age. This applies to Eastmoney and TickFlow.
            raise ValueError("source emitted_at is in the future")
        source_age_seconds = source_age_delta_seconds
        source_acceptance_status = "ACCEPTED"
        key = (source_runtime_instance_id, source_sequence)
        if source_provider == "tickflow":
            validate_tickflow_source_clock(source, now)
            key = (source_repo_sha, source_sequence, source_emitted_at_utc,
                   source_stat.st_ino, source_stat.st_mtime_ns)
        if key == last_key and last_evaluation is not None:
            evaluation = last_evaluation
            poll_status = "UNCHANGED"
        else:
            analysis_started = time.perf_counter()
            evaluation = (
                evaluate_tickflow_observation_payload(source, now_utc=now)
                if source_provider == "tickflow"
                else evaluate_cn_observation_payload(source)
            )
            analysis_status = "PASS"
            if isinstance(evaluation, dict):
                # A successful research evaluation may still contain
                # provisional bars. Only an explicit PROVEN attestation
                # changes the bar state; strategy admission stays closed.
                bar_state = (
                    "PROVEN"
                    if evaluation.get("bar_finality") == "PROVEN"
                    else "PROVISIONAL"
                )
            radar_analysis_latency_ms = round(
                (time.perf_counter() - analysis_started) * 1000,
                3,
            )
            radar_analysis_performed = True
            last_key = key
            last_evaluation = evaluation
            poll_status = "PASS"
    except Exception as exc:
        analysis_status = "ERROR"
        if source_acceptance_status == "NOT_READ":
            source_acceptance_status = "REJECTED"
        reasons.append(f"SOURCE_OR_ANALYSIS_ERROR:{type(exc).__name__}")

    completed_at = datetime.now(timezone.utc)
    if source_emitted is not None:
        source_delta_ms = (
            completed_at - source_emitted.astimezone(timezone.utc)
        ).total_seconds() * 1000
        # Do not turn a clock reversal into fake 0ms Data->Radar latency.
        source_age_seconds = (
            round(source_delta_ms / 1000, 6) if source_delta_ms >= 0 else None
        )
        if radar_analysis_performed and source_delta_ms >= 0:
            data_to_radar_latency_ms = round(source_delta_ms, 3)

    payload = {
        "type": "cn_radar_research_heartbeat",
        "runtime_instance_id": runtime_id,
        "worker_repo_sha": worker_repo_sha,
        "host_id": host_id,
        "sequence": cycle,
        "emitted_at_utc": completed_at.isoformat(),
        "source_path": source_path,
        "source_repo_sha": source_repo_sha,
        "source_runtime_instance_id": source_runtime_instance_id,
        "source_sequence": source_sequence,
        "source_emitted_at_utc": source_emitted_at_utc,
        "source_age_seconds": source_age_seconds,
        "source_acceptance_status": source_acceptance_status,
        "analysis_status": analysis_status,
        "bar_state": bar_state,
        "strategy_admission": strategy_admission,
        "radar_analysis_performed": radar_analysis_performed,
        "radar_analysis_latency_ms": radar_analysis_latency_ms,
        "data_to_radar_latency_ms": data_to_radar_latency_ms,
        "poll_status": poll_status,
        "evaluation": evaluation,
        "reasons": reasons,
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
Description=STOCK RAZOR A-share cloud Radar research worker
After=$SOURCE_SERVICE
Wants=$SOURCE_SERVICE

[Service]
Type=simple
WorkingDirectory=$INSTALL_ROOT/repo
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$INSTALL_ROOT/repo
Environment=STOCK_RAZOR_WORKER_REPO_SHA=$REPO_REF
Environment=STOCK_RAZOR_CN_OBSERVATION_PATH=$SOURCE_PATH
Environment=STOCK_RAZOR_CN_RADAR_SOURCE_PROVIDER=$SOURCE_PROVIDER
Environment=STOCK_RAZOR_CN_RADAR_STATUS_PATH=$STATUS_PATH
Environment=STOCK_RAZOR_CN_RADAR_POLL_SECONDS=$POLL_SECONDS
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
ReadOnlyPaths=-/run/stock-razor-cn-tickflow

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl is-active "$SERVICE_NAME"
