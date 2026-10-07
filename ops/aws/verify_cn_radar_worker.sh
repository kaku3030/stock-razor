#!/usr/bin/env bash
set -euo pipefail

expected_worker_sha="${1:?expected worker sha required}"
expected_source_sha="${2:?expected source sha required}"
service="stock-razor-cn-radar.service"
status="/run/stock-razor-cn-radar/latest-research-state.json"
python_bin="/opt/stock-razor-cn-radar/venv/bin/python"

for _ in $(seq 1 24); do
  if systemctl is-active --quiet "$service" && [[ -s "$status" ]]; then
    if "$python_bin" - "$status" "$expected_worker_sha" "$expected_source_sha" <<'PY'
import json
import sys

path, worker_sha, source_sha = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

assert payload.get("type") == "cn_radar_research_heartbeat"
assert payload.get("worker_repo_sha") == worker_sha
assert payload.get("expected_source_repo_sha") == source_sha
assert int(payload.get("sequence") or 0) > 0
assert payload.get("research_only") is True
assert payload.get("can_confirm_signal") is False
assert payload.get("radar_admission") == "BLOCKED"
assert payload.get("live_trade") is False

evaluation = payload.get("evaluation") or {}
assert evaluation.get("status") == "PASS"
assert evaluation.get("source_repo_sha") == source_sha
assert evaluation.get("research_only") is True
assert evaluation.get("can_confirm_signal") is False
assert evaluation.get("radar_admission") == "BLOCKED"
assert evaluation.get("live_trade") is False

symbols = evaluation.get("symbols") or []
assert symbols
for item in symbols:
    assert item.get("status") == "RESEARCH_STATE"
    assert item.get("research_only") is True
    assert item.get("can_confirm_signal") is False
    assert item.get("radar_admission") == "BLOCKED"
    assert item.get("live_trade") is False
    tech = item.get("technical") or {}
    daily = tech.get("daily") or {}
    hourly = tech.get("hourly") or {}
    intraday = tech.get("intraday") or {}
    assert int((daily.get("quality") or {}).get("bars") or 0) >= 120
    assert int((hourly.get("quality") or {}).get("bars") or 0) >= 60
    assert int((intraday.get("quality") or {}).get("bars") or 0) >= 60
    assert (hourly.get("quality") or {}).get("status") == "partial"
    assert (intraday.get("quality") or {}).get("status") == "partial"
    hourly_warnings = set((hourly.get("quality") or {}).get("warnings") or [])
    intraday_warnings = set((intraday.get("quality") or {}).get("warnings") or [])
    assert "1h_timestamp_semantics_unverified" in hourly_warnings
    assert "1h_currentness_unproven" in hourly_warnings
    assert "15m_timestamp_semantics_unverified" in intraday_warnings
    assert "15m_currentness_unproven" in intraday_warnings
PY
    then
      systemctl is-enabled "$service"
      systemctl is-active "$service"
      test "$(systemctl show "$service" -p PrivateNetwork --value)" = "yes"
      test "$(systemctl show "$service" -p NoNewPrivileges --value)" = "yes"
      "$python_bin" - "$status" <<'PY'
import json,sys
with open(sys.argv[1], encoding="utf-8") as handle:
    p=json.load(handle)
print(json.dumps({
    "type":p.get("type"),
    "worker_repo_sha":p.get("worker_repo_sha"),
    "expected_source_repo_sha":p.get("expected_source_repo_sha"),
    "sequence":p.get("sequence"),
    "poll_status":p.get("poll_status"),
    "symbols":[
        {
            "symbol":x.get("symbol"),
            "status":x.get("status"),
            "daily_bars":(((x.get("technical") or {}).get("daily") or {}).get("quality") or {}).get("bars"),
            "hourly_bars":(((x.get("technical") or {}).get("hourly") or {}).get("quality") or {}).get("bars"),
            "intraday_bars":(((x.get("technical") or {}).get("intraday") or {}).get("quality") or {}).get("bars"),
        }
        for x in ((p.get("evaluation") or {}).get("symbols") or [])
    ],
    "radar_admission":p.get("radar_admission"),
    "live_trade":p.get("live_trade"),
},separators=(",",":")))
PY
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
