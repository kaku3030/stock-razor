#!/usr/bin/env bash
set -euo pipefail
expected_sha="${1:?expected sha required}"
status=/run/stock-razor-us-livefeed/latest-heartbeat.json
snapshot=/run/stock-razor-us-livefeed/canonical-market-snapshot.json
python_bin=/opt/stock-razor-opend-client/venv/bin/python

for _ in $(seq 1 18); do
  if systemctl is-active --quiet stock-razor-us-livefeed.service && [[ -s "$status" ]] && [[ -s "$snapshot" ]]; then
    if "$python_bin" - "$status" "$snapshot" "$expected_sha" 2>/dev/null <<'PY'
import json
import sys

status_path, snapshot_path, expected_sha = sys.argv[1:]
with open(status_path, encoding="utf-8") as handle:
    heartbeat = json.load(handle)
with open(snapshot_path, encoding="utf-8") as handle:
    snapshot = json.load(handle)

export = heartbeat.get("canonical_snapshot_export") or {}
assert heartbeat.get("repo_sha") == expected_sha
assert int(heartbeat.get("event_count") or 0) > 0
assert export.get("status") == "PASS"
assert export.get("schema") == "stock_razor_canonical_market_snapshot_v1"
assert export.get("repo_sha") == expected_sha
assert snapshot.get("schema") == "stock_razor_canonical_market_snapshot_v1"
assert snapshot.get("repo_sha") == expected_sha
assert snapshot.get("runtime_instance_id") == heartbeat.get("runtime_instance_id")
snapshot_sequence = int(snapshot.get("sequence") or -1)
assert snapshot_sequence == int(export.get("sequence") or -2)
assert snapshot_sequence > 0
assert export.get("last_write_utc")
assert snapshot.get("delivery_mode") == "UNKNOWN"
assert snapshot.get("bar_closure") == "UNPROVEN"
assert snapshot.get("radar_admission") == "BLOCKED"
assert snapshot.get("live_trade") is False
PY
    then
      systemctl is-enabled stock-razor-us-livefeed.service
      systemctl is-active stock-razor-us-livefeed.service
      cat "$status"
      printf '\n'
      echo "CANONICAL_SNAPSHOT_EXPORT=PASS"
      echo "CANONICAL_SNAPSHOT_PATH=$snapshot"
      exit 0
    fi
  fi
  sleep 5
done
echo US_OPEND_LIVEFEED_ACCEPTANCE_TIMEOUT >&2
exit 1
