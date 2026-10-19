#!/usr/bin/env bash
set -euo pipefail

expected_worker_sha="${1:?expected worker sha required}"
expected_provider="${2:-eastmoney}"
case "$expected_provider" in eastmoney|tickflow) ;; *) exit 2;; esac
service="stock-razor-cn-radar.service"
status="/run/stock-razor-cn-radar/latest-research-state.json"
python_bin="/opt/stock-razor-cn-radar/venv/bin/python"

for _ in $(seq 1 24); do
  if systemctl is-active --quiet "$service" && [[ -s "$status" ]]; then
    if "$python_bin" - "$status" "$expected_worker_sha" "$expected_provider" <<'PY'
import json
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

status_path, expected_worker_sha, expected_provider = sys.argv[1:]
is_tickflow = expected_provider == "tickflow"
with open(status_path, encoding="utf-8") as handle:
    payload = json.load(handle)

assert payload.get("type") == "cn_radar_research_heartbeat"
assert payload.get("worker_repo_sha") == expected_worker_sha
assert int(payload.get("sequence") or 0) > 0
assert payload.get("poll_status") in {"PASS", "UNCHANGED"}
assert payload.get("research_only") is True
assert payload.get("can_confirm_signal") is False
assert payload.get("radar_admission") == "BLOCKED"
assert payload.get("live_trade") is False
assert not payload.get("reasons")

radar_analysis_performed = payload.get("radar_analysis_performed")
radar_analysis_latency_ms = payload.get("radar_analysis_latency_ms")
data_to_radar_latency_ms = payload.get("data_to_radar_latency_ms")
assert isinstance(radar_analysis_performed, bool)
if radar_analysis_performed:
    assert payload.get("poll_status") == "PASS"
    assert (
        isinstance(radar_analysis_latency_ms, (int, float))
        and not isinstance(radar_analysis_latency_ms, bool)
        and radar_analysis_latency_ms >= 0
    )
    assert (
        isinstance(data_to_radar_latency_ms, (int, float))
        and not isinstance(data_to_radar_latency_ms, bool)
        and data_to_radar_latency_ms >= 0
    )
else:
    assert radar_analysis_latency_ms is None
    assert data_to_radar_latency_ms is None

evaluation = payload.get("evaluation") or {}
assert evaluation.get("schema") == "stock_razor_cn_radar_research_v1"
assert evaluation.get("status") == "PASS"
assert evaluation.get("research_only") is True
assert evaluation.get("can_confirm_signal") is False
assert evaluation.get("radar_admission") == "BLOCKED"
assert evaluation.get("live_trade") is False
if is_tickflow:
    assert evaluation.get("provider_requests") == 0
    assert evaluation.get("bar_finality") == "NOT_VERIFIED"
    assert evaluation.get("source_arbiter_admission") == "BLOCKED"
    assert evaluation.get("intraday_timestamp_semantics_proven") is False
    assert evaluation.get("provider_policy") == "TICKFLOW_CACHE_HISTORICAL_RESEARCH_ONLY"
    assert evaluation.get("provider_lineages") == ["tickflow"]
    assert evaluation.get("source_repo_sha") == payload.get("source_repo_sha")
    assert type(payload.get("source_sequence")) is int and payload["source_sequence"] > 0
    assert payload.get("source_age_seconds") is not None
    with open("/run/stock-razor-cn-tickflow/latest-research-observation.json", "rb") as source_file:
        raw = source_file.read(64_000_001)
    assert len(raw) <= 64_000_000
    source = json.loads(raw)
    assert source.get("provider") == "TICKFLOW_PREMIUM"
    assert source.get("live_trade") is False
    assert source.get("radar_admission") == "BLOCKED"
    assert payload.get("source_repo_sha") == source.get("repo_sha")
    assert payload.get("source_sequence") == source.get("sequence")
    assert payload.get("source_emitted_at_utc") == source.get("observed_at_utc")
    observed = datetime.fromisoformat(source["observed_at_utc"])
    now = datetime.now(timezone.utc)
    max_age = 1080 if now.astimezone(ZoneInfo("Asia/Shanghai")).weekday() >= 5 else 360
    assert observed.tzinfo is not None and 0 <= (now - observed).total_seconds() <= max_age
else:
    assert evaluation.get("intraday_timestamp_semantics_proven") is True
assert isinstance(evaluation.get("intraday_currentness_proven"), bool)

symbols = evaluation.get("symbols") or {}
assert symbols
research_symbols = set(evaluation.get("research_state_symbols") or [])
assert research_symbols == set(symbols)
if is_tickflow:
    # Verify the independently read producer set, not a stale four-symbol copy.
    # Adding an observation ETF must not break deployment or hide a dropped ETF.
    source_symbols = source.get("symbols")
    assert isinstance(source_symbols, dict) and source_symbols
    assert all(isinstance(s, str) and len(s) == 9 and
               s[:6].isdigit() and s[6:] in {".SH", ".SZ", ".BJ"}
               for s in source_symbols)
    assert set(source_symbols) =="159611.SZ", "159209.SZ", "518880.SH", "512730.SH", "159363.SZ"}
    assert research_symbols == {s[:6] for s in source_symbols}
for symbol, item in symbols.items():
    assert item.get("status") == "RESEARCH_STATE"
    assert item.get("research_only") is True
    assert item.get("can_confirm_signal") is False
    assert item.get("signal_permission") == "record_only"
    assert item.get("intraday_timestamp_semantics_proven") is (not is_tickflow)
    assert isinstance(item.get("intraday_currentness_proven"), bool)
    technical = item.get("technical") or {}
    assert technical
    frames = item.get("frame_provenance") or {}
    assert set(frames) == {"1d", "60m", "15m"}
    risk_flags = set(technical.get("risk_flags") or [])
    if is_tickflow:
        assert "cn_intraday_timestamp_semantics_unproven" in risk_flags
        assert "tickflow_bar_finality_not_verified" in risk_flags
        assert item.get("intraday_currentness_proven") is False
        assert technical["hourly"]["quality"]["is_partial_bar"] is True
        assert technical["intraday"]["quality"]["is_partial_bar"] is True
        for frame in frames.values():
            assert frame.get("provider_used") == "TICKFLOW_PREMIUM"
            assert frame.get("bar_finality") == "NOT_VERIFIED"
    else:
        assert "cn_intraday_timestamp_semantics_unproven" not in risk_flags
    if item.get("intraday_currentness_proven") is True:
        assert "cn_intraday_currentness_unproven" not in risk_flags
    else:
        assert "cn_intraday_currentness_unproven" in risk_flags

assert evaluation.get("intraday_currentness_proven") is all(
    item.get("intraday_currentness_proven") is True
    for item in symbols.values()
)
print("CN_RADAR_SYMBOLS=" + ",".join(sorted(symbols)))
PY
    then
      systemctl is-enabled "$service"
      systemctl is-active "$service"
      test "$(systemctl show "$service" -p PrivateNetwork --value)" = "yes"
      test "$(systemctl show "$service" -p NoNewPrivileges --value)" = "yes"
      echo "CN_RADAR_WORKER_VERIFY=PASS"
      echo "RADAR_ADMISSION=BLOCKED"
      echo "LIVE_TRADE=NO"
      exit 0
    fi
  fi
  sleep 5
done

echo CN_RADAR_WORKER_ACCEPTANCE_TIMEOUT >&2
systemctl status "$service" --no-pager >&2 || true
journalctl -u "$service" -n 100 --no-pager >&2 || true
exit 1
