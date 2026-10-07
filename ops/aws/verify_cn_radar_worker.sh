#!/usr/bin/env bash
set -euo pipefail

expected_worker_sha="${1:?expected worker sha required}"
expected_source_sha="${2:?expected source sha required}"
service="stock-razor-cn-radar.service"
status="/run/stock-razor-cn-radar/latest-research-state.json"
python_bin="/opt/stock-razor-cn-radar/venv/bin/python"

for _ in $(seq 1 36); do
  if systemctl is-active --quiet "$service" && [[ -s "$status" ]]; then
    if summary="$("$python_bin" - "$status" "$expected_worker_sha" "$expected_source_sha" <<'PY'
import json
import sys

path, expected_worker_sha, expected_source_sha = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

assert payload.get("type") == "cn_radar_research_heartbeat"
assert payload.get("worker_repo_sha") == expected_worker_sha
assert payload.get("expected_source_repo_sha") == expected_source_sha
assert int(payload.get("sequence") or 0) > 0
assert payload.get("research_only") is True
assert payload.get("can_confirm_signal") is False
assert payload.get("radar_admission") == "BLOCKED"
assert payload.get("live_trade") is False

evaluation = payload.get("evaluation") or {}
assert evaluation.get("status") in {"PASS", "UNCHANGED"}
assert evaluation.get("source_repo_sha") == expected_source_sha
assert evaluation.get("research_only") is True
assert evaluation.get("can_confirm_signal") is False
assert evaluation.get("radar_admission") == "BLOCKED"
assert evaluation.get("live_trade") is False

analysis = evaluation.get("analysis") or {}
assert analysis.get("schema") == "stock_razor_cn_radar_research_v1"
assert analysis.get("status") == "PASS"
assert analysis.get("source_repo_sha") == expected_source_sha
assert analysis.get("research_only") is True
assert analysis.get("can_confirm_signal") is False
assert analysis.get("radar_admission") == "BLOCKED"
assert analysis.get("live_trade") is False
assert analysis.get("intraday_timestamp_semantics_proven") is False
assert analysis.get("intraday_currentness_proven") is False

symbols = analysis.get("symbols") or {}
research_symbols = set(analysis.get("research_state_symbols") or [])
assert symbols
assert research_symbols == set(symbols)
for symbol, item in symbols.items():
    assert item.get("status") == "RESEARCH_STATE"
    assert item.get("signal_permission") == "record_only"
    assert item.get("research_only") is True
    assert item.get("can_confirm_signal") is False
    technical = item.get("technical") or {}
    assert (technical.get("daily") or {}).get("timeframe") == "1d"
    assert (technical.get("hourly") or {}).get("timeframe") == "1h"
    assert (technical.get("intraday") or {}).get("timeframe") == "15m"
    flags = set(technical.get("risk_flags") or [])
    assert "cn_intraday_timestamp_semantics_unproven" in flags
    assert "cn_intraday_currentness_unproven" in flags

print(json.dumps({
    "status": "PASS",
    "worker_repo_sha": payload.get("worker_repo_sha"),
    "source_repo_sha": evaluation.get("source_repo_sha"),
    "symbols": sorted(symbols),
    "source_sequence": evaluation.get("source_sequence"),
    "radar_admission": payload.get("radar_admission"),
    "live_trade": payload.get("live_trade"),
}, separators=(",", ":")))
PY
)"; then
      systemctl is-enabled "$service"
      systemctl is-active "$service"
      test "$(systemctl show "$service" -p PrivateNetwork --value)" = "yes"
      test "$(systemctl show "$service" -p NoNewPrivileges --value)" = "yes"
      printf '%s\n' "$summary"
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
journalctl -u "$service" -n 80 --no-pager >&2 || true
exit 1
