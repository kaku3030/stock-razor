#!/usr/bin/env bash
set -euo pipefail
expected_sha="${1:?expected sha required}"
status=/run/stock-razor-us-livefeed/latest-heartbeat.json
snapshot=/run/stock-razor-us-livefeed/canonical-market-snapshot.json
python_bin=/opt/stock-razor-opend-client/venv/bin/python

for _ in $(seq 1 18); do
  if systemctl is-active --quiet stock-razor-us-livefeed.service && [[ -s "$status" ]] && [[ -s "$snapshot" ]]; then
    if "$python_bin" - "$status" "$snapshot" "$expected_sha" <<'PY'
import json
import math
import sys

status_path, snapshot_path, expected_sha = sys.argv[1:]
with open(status_path, encoding="utf-8") as handle:
    heartbeat = json.load(handle)
with open(snapshot_path, encoding="utf-8") as handle:
    snapshot = json.load(handle)

export = heartbeat.get("canonical_snapshot_export") or {}
assert heartbeat.get("repo_sha") == expected_sha
assert int(heartbeat.get("event_count") or 0) > 0
closure = heartbeat.get("k1m_closure_qualification") or {}
closure_summary = heartbeat.get("k1m_closure_qualification_summary")
currentness_summary = heartbeat.get("k1m_currentness_summary")
assert closure_summary in {"UNKNOWN", "PASS", "FAIL", "NOT_APPLICABLE"}
assert currentness_summary in {"UNKNOWN", "PASS", "FAIL", "NOT_APPLICABLE"}
assert set(closure) == set(heartbeat.get("symbols") or [])
for item in closure.values():
    assert item.get("status") in {"UNKNOWN", "PASS", "FAIL", "NOT_APPLICABLE"}
    assert item.get("can_promote") is False
expected_bar_closure = (
    "PROVEN"
    if currentness_summary == "PASS" and closure_summary == "PASS"
    else "UNPROVEN"
)
assert heartbeat.get("bar_closure_evidence_state") == expected_bar_closure
assert heartbeat.get("bar_closure") == expected_bar_closure
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

quote_right = heartbeat.get("quote_right_evidence") or {}
assert quote_right.get("query_status") in {"UNKNOWN", "PASS", "BLOCKED"}
assert quote_right.get("normalized_quote_right")
assert quote_right.get("delivery_mode") in {"UNKNOWN", "REALTIME"}
age = quote_right.get("age_seconds")
max_age = quote_right.get("max_age_seconds")
realtime_rights = {"LV1", "LEVEL1", "LV2", "LEVEL2", "LV3", "LEVEL3"}
fresh_realtime = (
    quote_right.get("query_status") == "PASS"
    and quote_right.get("normalized_quote_right") in realtime_rights
    and isinstance(age, (int, float))
    and math.isfinite(age)
    and age >= 0
    and isinstance(max_age, (int, float))
    and math.isfinite(max_age)
    and max_age > 0
    and age <= max_age
)
expected_delivery_mode = "REALTIME" if fresh_realtime else "UNKNOWN"
assert quote_right.get("delivery_mode") == expected_delivery_mode
assert heartbeat.get("delivery_mode") == expected_delivery_mode
assert snapshot.get("delivery_mode") == expected_delivery_mode
assert export.get("delivery_mode") == expected_delivery_mode
assert snapshot.get("bar_closure") == expected_bar_closure
assert export.get("bar_closure") == expected_bar_closure
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
