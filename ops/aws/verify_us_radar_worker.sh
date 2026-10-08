#!/usr/bin/env bash
set -euo pipefail

expected_worker_sha="${1:?expected worker sha required}"
expected_source_sha="${2:?expected source sha required}"
service="stock-razor-us-radar.service"
status="/run/stock-razor-us-radar/latest-research-state.json"
python_bin="/opt/stock-razor-us-radar/venv/bin/python"

for _ in $(seq 1 24); do
  if systemctl is-active --quiet "$service" && [[ -s "$status" ]]; then
    if "$python_bin" - "$status" "$expected_worker_sha" "$expected_source_sha" <<'PY'
import json
import sys

status_path, expected_worker_sha, expected_source_sha = sys.argv[1:]
with open(status_path, encoding="utf-8") as handle:
    payload = json.load(handle)

assert payload.get("type") == "us_radar_research_heartbeat"
assert payload.get("worker_repo_sha") == expected_worker_sha
assert payload.get("expected_source_repo_sha") == expected_source_sha
assert int(payload.get("sequence") or 0) > 0
assert payload.get("research_only") is True
assert payload.get("can_confirm_signal") is False
assert payload.get("radar_admission") == "BLOCKED"
assert payload.get("live_trade") is False

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

daily_history = payload.get("daily_history") or {}
assert daily_history.get("status") == "PASS"
assert daily_history.get("historical_query") is True
assert daily_history.get("currentness_proven") is False
assert daily_history.get("bar_closure_promotion_authorized") is False
assert daily_history.get("research_only") is True
assert daily_history.get("can_confirm_signal") is False
assert daily_history.get("radar_admission") == "BLOCKED"
assert daily_history.get("live_trade") is False
daily_symbols = daily_history.get("symbols") or {}
assert daily_symbols
for symbol, item in daily_symbols.items():
    assert int(item.get("row_count") or 0) >= 120
    assert item.get("latest_date")

evaluation = payload.get("evaluation") or {}
assert evaluation.get("source_repo_sha") == expected_source_sha
assert evaluation.get("source_delivery_mode") in {"UNKNOWN", "REALTIME"}
assert evaluation.get("source_bar_closure") in {"UNPROVEN", "PROVEN"}
assert evaluation.get("source_radar_admission") == "BLOCKED"
assert evaluation.get("source_live_trade") is False
assert evaluation.get("research_only") is True
assert evaluation.get("can_confirm_signal") is False

diagnostics = evaluation.get("admission_diagnostics") or {}
assert diagnostics.get("decision") == "BLOCKED"
assert diagnostics.get("promotion_authorized") is False
assert diagnostics.get("source_radar_admission") == "BLOCKED"
assert diagnostics.get("source_live_trade") is False
assert diagnostics.get("delivery_mode_realtime") is (
    evaluation.get("source_delivery_mode") == "REALTIME"
)
assert diagnostics.get("bar_closure_proven") is (
    evaluation.get("source_bar_closure") == "PROVEN"
)
assert diagnostics.get("minimum_source_prerequisites_met") is (
    diagnostics.get("delivery_mode_realtime") is True
    and diagnostics.get("bar_closure_proven") is True
)
diagnostic_reasons = set(diagnostics.get("reasons") or [])
assert "PROMOTION_NOT_AUTHORIZED" in diagnostic_reasons

if evaluation.get("status") in {"PASS", "UNCHANGED"}:
    symbols = evaluation.get("symbols") or []
    assert symbols
    for item in symbols:
        if item.get("status") != "RESEARCH_STATE":
            continue
        technical_state = item.get("technical_state") or {}
        technical = technical_state.get("technical") or {}
        daily_state = technical.get("daily") or {}
        quality = daily_state.get("quality") or {}
        assert quality.get("status") != "missing"
        assert int(quality.get("bars") or 0) >= 60
        assert "1d_data_missing" not in set(quality.get("warnings") or [])
        assert technical_state.get("research_only") is True
        assert technical_state.get("can_confirm_signal") is False

assert evaluation.get("status") in {"PASS", "UNCHANGED", "BLOCKED"}
if evaluation.get("status") == "BLOCKED":
    reasons = set(evaluation.get("reasons") or [])
    allowed = {
        "SOURCE_EXPORT_STALE",
        "SOURCE_EXPORT_FROM_FUTURE",
        "SOURCE_SEQUENCE_REGRESSION",
    }
    assert reasons
    assert reasons.issubset(allowed)
PY
    then
      systemctl is-enabled "$service"
      systemctl is-active "$service"
      test "$(systemctl show "$service" -p PrivateNetwork --value)" = "yes"
      test "$(systemctl show "$service" -p NoNewPrivileges --value)" = "yes"
      cat "$status"
      printf '\n'
      echo "US_RADAR_WORKER_VERIFY=PASS"
      echo "RADAR_ADMISSION=BLOCKED"
      echo "LIVE_TRADE=NO"
      exit 0
    fi
  fi
  sleep 5
done

echo US_RADAR_WORKER_ACCEPTANCE_TIMEOUT >&2
systemctl status "$service" --no-pager >&2 || true
journalctl -u "$service" -n 80 --no-pager >&2 || true
exit 1
