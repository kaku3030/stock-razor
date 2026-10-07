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

warm_start = heartbeat.get("warm_start") or {}
assert warm_start.get("status") == "PASS"
assert warm_start.get("historical_query") is True
assert warm_start.get("realtime_currentness_proven") is False
assert warm_start.get("bar_closure_promotion_authorized") is False
assert warm_start.get("radar_admission") == "BLOCKED"
assert warm_start.get("live_trade") is False
warm_symbols = warm_start.get("symbols") or {}
expected_symbols = set(heartbeat.get("symbols") or [])
assert set(warm_symbols) == expected_symbols
assert expected_symbols
for symbol, item in warm_symbols.items():
    assert item.get("status") == "PASS"
    assert int(item.get("planned_bar_count") or 0) == 390
    assert int(item.get("seeded_count") or 0) + int(item.get("unchanged_count") or 0) == 390
    assert item.get("closure_anchor_time_key")
assert int(warm_start.get("seeded_total") or 0) + int(warm_start.get("unchanged_total") or 0) == 390 * len(expected_symbols)

canonical_cache = heartbeat.get("canonical_cache") or {}
assert set(canonical_cache) == expected_symbols
for symbol in expected_symbols:
    item = canonical_cache.get(symbol) or {}
    assert int(item.get("bar_count") or 0) >= 390
    assert int(item.get("bar_count_5m") or 0) > 0
    assert int(item.get("bar_count_15m") or 0) > 0
    assert int(item.get("bar_count_1h") or 0) > 0

snapshot_symbols = snapshot.get("symbols") or {}
assert set(snapshot_symbols) == expected_symbols
for symbol in expected_symbols:
    frames = (snapshot_symbols.get(symbol) or {}).get("timeframes") or {}
    assert len(frames.get("1m") or []) >= 390
    assert len(frames.get("5m") or []) > 0
    assert len(frames.get("15m") or []) > 0
    assert len(frames.get("1h") or []) > 0

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
