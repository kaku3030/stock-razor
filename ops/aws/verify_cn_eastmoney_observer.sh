#!/usr/bin/env bash
set -euo pipefail

expected_sha="${1:?expected repo sha required}"
service="stock-razor-cn-eastmoney.service"
status="/run/stock-razor-cn-eastmoney/latest-observation.json"
python_bin="/opt/stock-razor-cn-eastmoney/venv/bin/python"

for _ in $(seq 1 24); do
  if systemctl is-active --quiet "$service" && [[ -s "$status" ]]; then
    if "$python_bin" - "$status" "$expected_sha" <<'PY'
import json
import sys

status_path, expected_sha = sys.argv[1:]
with open(status_path, encoding="utf-8") as handle:
    payload = json.load(handle)

assert payload.get("schema") == "stock_razor_cn_eastmoney_observation_v1"
assert payload.get("repo_sha") == expected_sha
assert int(payload.get("sequence") or 0) > 0
assert payload.get("provider") == "eastmoney"
assert payload.get("provider_lineage") == "eastmoney"
assert payload.get("intraday_timestamp_semantics_proven") is False
assert payload.get("intraday_currentness_proven") is False
assert payload.get("research_only") is True
assert payload.get("can_confirm_signal") is False
assert payload.get("radar_admission") == "BLOCKED"
assert payload.get("live_trade") is False
assert payload.get("status") == "PASS"

symbols = payload.get("symbols") or {}
assert symbols
for symbol, item in symbols.items():
    assert item.get("status") == "PASS"
    assert item.get("provider") == "eastmoney"
    assert item.get("radar_admission") == "BLOCKED"
    assert item.get("live_trade") is False
    frames = item.get("timeframes") or {}
    assert set(frames) == {"1d", "60m", "15m"}
    for timeframe in ("1d", "60m", "15m"):
        frame = frames[timeframe]
        assert frame.get("status") == "PASS"
        assert int(frame.get("row_count") or 0) > 0
        assert frame.get("currentness") == "UNPROVEN"
        assert frame.get("rows")
    assert frames["1d"].get("timestamp_semantic") == "DAILY_DATE"
    assert frames["60m"].get("timestamp_semantic") == "UNKNOWN"
    assert frames["15m"].get("timestamp_semantic") == "UNKNOWN"
PY
    then
      systemctl is-enabled "$service"
      systemctl is-active "$service"
      cat "$status"
      printf '\n'
      echo "CN_EASTMONEY_CLOUD_VERIFY=PASS"
      echo "RADAR_ADMISSION=BLOCKED"
      echo "LIVE_TRADE=NO"
      exit 0
    fi
  fi
  sleep 5
done

echo CN_EASTMONEY_CLOUD_ACCEPTANCE_TIMEOUT >&2
systemctl status "$service" --no-pager >&2 || true
journalctl -u "$service" -n 100 --no-pager >&2 || true
exit 1
