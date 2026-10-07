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
