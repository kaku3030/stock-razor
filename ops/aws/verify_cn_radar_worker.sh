#!/usr/bin/env bash
set -euo pipefail

expected_worker_sha="${1:?expected worker sha required}"
service="stock-razor-cn-radar.service"
status="/run/stock-razor-cn-radar/latest-research-state.json"
python_bin="/opt/stock-razor-cn-radar/venv/bin/python"

for _ in $(seq 1 24); do
  if systemctl is-active --quiet "$service" && [[ -s "$status" ]]; then
    if "$python_bin" - "$status" "$expected_worker_sha" <<'PY'
import json
import sys

status_path, expected_worker_sha = sys.argv[1:]
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

evaluation = payload.get("evaluation") or {}
assert evaluation.get("schema") == "stock_razor_cn_radar_research_v1"
assert evaluation.get("status") == "PASS"
assert evaluation.get("research_only") is True
assert evaluation.get("can_confirm_signal") is False
assert evaluation.get("radar_admission") == "BLOCKED"
assert evaluation.get("live_trade") is False
assert evaluation.get("intraday_timestamp_semantics_proven") is True
assert isinstance(evaluation.get("intraday_currentness_proven"), bool)

symbols = evaluation.get("symbols") or {}
assert symbols
research_symbols = set(evaluation.get("research_state_symbols") or [])
assert research_symbols == set(symbols)
for symbol, item in symbols.items():
    assert item.get("status") == "RESEARCH_STATE"
    assert item.get("research_only") is True
    assert item.get("can_confirm_signal") is False
    assert item.get("signal_permission") == "record_only"
    assert item.get("intraday_timestamp_semantics_proven") is True
    assert isinstance(item.get("intraday_currentness_proven"), bool)
    technical = item.get("technical") or {}
    assert technical
    frames = item.get("frame_provenance") or {}
    assert set(frames) == {"1d", "60m", "15m"}
    risk_flags = set(technical.get("risk_flags") or [])
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
