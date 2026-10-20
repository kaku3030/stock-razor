#!/usr/bin/env bash
set -euo pipefail
expected_sha="${1:?expected sha required}"
expected_ab_blend="${2:-0}"
[[ "$expected_ab_blend" =~ ^[01]$ ]] || { echo "AB_BLEND_EXPECTATION_INVALID" >&2; exit 2; }
status=/run/stock-razor-us-livefeed/latest-heartbeat.json
snapshot=/run/stock-razor-us-livefeed/canonical-market-snapshot.json
daily=/run/stock-razor-us-livefeed/daily-history.json
python_bin=/opt/stock-razor-opend-client/venv/bin/python

for _ in $(seq 1 18); do
  if systemctl is-active --quiet stock-razor-us-livefeed.service && [[ -s "$status" ]] && [[ -s "$snapshot" ]] && [[ -s "$daily" ]]; then
    if "$python_bin" - "$status" "$snapshot" "$daily" "$expected_sha" "$expected_ab_blend" <<'PY'
import json
import math
import sys

status_path, snapshot_path, daily_path, expected_sha, expected_ab_blend = sys.argv[1:]
with open(status_path, encoding="utf-8") as handle:
    heartbeat = json.load(handle)
with open(snapshot_path, encoding="utf-8") as handle:
    snapshot = json.load(handle)
with open(daily_path, encoding="utf-8") as handle:
    daily = json.load(handle)

export = heartbeat.get("canonical_snapshot_export") or {}
assert heartbeat.get("repo_sha") == expected_sha
assert heartbeat.get("research_only") is True
assert heartbeat.get("can_confirm_signal") is False
assert heartbeat.get("radar_admission") == "BLOCKED"
assert heartbeat.get("live_trade") is False
# No RTH minute callbacks are required on a provider-confirmed closed
# or extended-hours session. This is NOT proof of fresh realtime delivery.
observed_data_events = int(heartbeat.get("event_count") or 0)
verified_non_regular = (
    heartbeat.get("market_state_evidence") == "PASS"
    and heartbeat.get("cache_session_us") in {
        "closed", "premarket", "afterhours", "overnight"
    }
)
assert observed_data_events > 0 or verified_non_regular

warm_start = heartbeat.get("warm_start") or {}
assert warm_start.get("status") == "PASS"
assert warm_start.get("historical_query") is True
assert warm_start.get("realtime_currentness_proven") is False
assert warm_start.get("bar_closure_promotion_authorized") is False
assert warm_start.get("radar_admission") == "BLOCKED"
assert warm_start.get("live_trade") is False
assert int(warm_start.get("required_sessions") or 0) == 3
warm_symbols = warm_start.get("symbols") or {}
expected_symbols = set(heartbeat.get("symbols") or [])
AB_BLEND_SYMBOLS = {"US.QQQ", "US.SCHD", "US.KMLM", "US.GLD", "US.DBMF", "US.BTAL"}
assert heartbeat.get("ab_blend_enabled") is (expected_ab_blend == "1")
if expected_ab_blend == "1":
    assert AB_BLEND_SYMBOLS.issubset(expected_symbols)
    assert heartbeat.get("provider_subscription_ack") == "PASS"
assert set(warm_symbols) == expected_symbols
assert expected_symbols

# Runtime dynamic candidate observation is intentionally read-only.
# All configured US quote streams remain the protected baseline.
# A known-but-unverified provider quota may block a proposed addition,
# but the acceptance gate must never claim it subscribed/unsubscribed.
acknowledged = heartbeat.get("subscribed")
assert isinstance(acknowledged, list)
assert len(acknowledged) == len(expected_symbols)
assert all(isinstance(symbol, str) for symbol in acknowledged)
assert set(acknowledged) == expected_symbols

candidate = heartbeat.get("dynamic_subscription_preview")
assert isinstance(candidate, dict)
assert candidate.get("evidence_scope") == (
    "EXISTING_BRIDGE_ACK_ONLY_NOT_PROVIDER_RECONCILIATION"
)
assert type(candidate.get("acknowledged_count")) is int
assert candidate["acknowledged_count"] == len(expected_symbols)
assert type(candidate.get("provider_calls")) is int
assert candidate["provider_calls"] == 0
assert type(candidate.get("subscription_changes")) is int
assert candidate["subscription_changes"] == 0
assert candidate.get("radar_admission") == "BLOCKED"
assert candidate.get("source_arbiter_admission") == "BLOCKED"
assert candidate.get("paper_auto_ready") is False
assert candidate.get("live_trade") is False
additions = candidate.get("proposed_additions")
removals = candidate.get("proposed_removals")
assert isinstance(additions, list)
assert len(additions) <= 200
assert len(additions) == len(set(additions))
assert all(
    isinstance(symbol, str)
    and symbol.startswith("US.")
    and 4 <= len(symbol) <= 16
    for symbol in additions
)
assert removals == []  # Protected baseline cannot be proposed for removal.
if candidate.get("status") == "NO_CHANGE_PLAN":
    assert candidate.get("reason") == "DRY_RUN_NEVER_MUTATES"
    assert additions == []
elif candidate.get("status") == "BLOCKED":
    # The AWS owner has no verified fresh quota, so proposals to add
    # symbols are a blocked preview, not a new provider subscription.
    assert candidate.get("reason") == "FRESH_PROVIDER_QUOTA_NOT_VERIFIED"
    assert additions
else:
    # PLAN_ONLY, OBSERVER_EXCEPTION, invalid policy and absent evidence
    # must not masquerade as an accepted runtime deployment.
    raise AssertionError("US_OPEND_DYNAMIC_OBSERVER_UNQUALIFIED")
for symbol, item in warm_symbols.items():
    assert item.get("status") == "PASS"
    assert int(item.get("planned_bar_count") or 0) == 1170
    assert len(item.get("session_dates") or []) == 3
    methods = item.get("closure_methods") or []
    anchors = item.get("closure_anchor_time_keys") or []
    assert len(methods) == 3
    # The terminal full-grid row may be closed either on a prior NY date
    # or on the *same* NY date after the explicit 16:30 ET + 390-row guard.
    # Both remain historical, never a live closure/admission signal.
    terminal_methods = {
        "QUALIFIED_PRIOR_SESSION_FULL_GRID",
        "QUALIFIED_POST_SESSION_FULL_GRID",
    }
    assert set(methods) <= {"NEXT_TIME_KEY_PROGRESS"} | terminal_methods
    terminal_count = sum(method in terminal_methods for method in methods)
    assert terminal_count in {0, 1}
    if terminal_count:
        assert methods[-1] in terminal_methods
        assert len(anchors) == 2
        assert item.get("closure_anchor_time_key") is None
    else:
        assert methods == ["NEXT_TIME_KEY_PROGRESS"] * 3
        assert len(anchors) == 3
        assert item.get("closure_anchor_time_key")
    assert int(item.get("seeded_count") or 0) + int(item.get("unchanged_count") or 0) == 1170
    catchup_status = item.get("current_session_catchup_status")
    assert catchup_status in {"PASS", "NOT_APPLICABLE"}
    catchup_planned = int(item.get("current_session_catchup_planned_bar_count") or 0)
    catchup_seeded = int(item.get("current_session_catchup_seeded_count") or 0)
    catchup_unchanged = int(item.get("current_session_catchup_unchanged_count") or 0)
    assert catchup_seeded + catchup_unchanged == catchup_planned
    if catchup_status == "PASS":
        assert catchup_planned > 0
        assert item.get("current_session_catchup_date")
        assert item.get("current_session_catchup_unresolved_tail_time_key")
        assert item.get("current_session_catchup_closure_method") == "NEXT_TIME_KEY_PROGRESS"
        assert item.get("current_session_catchup_reason") is None
    else:
        assert catchup_planned == 0
        assert catchup_seeded == 0
        assert catchup_unchanged == 0
assert int(warm_start.get("seeded_total") or 0) + int(warm_start.get("unchanged_total") or 0) == 1170 * len(expected_symbols)
assert int(warm_start.get("current_session_catchup_seeded_total") or 0) == sum(
    int(item.get("current_session_catchup_seeded_count") or 0)
    for item in warm_symbols.values()
)
assert int(warm_start.get("current_session_catchup_unchanged_total") or 0) == sum(
    int(item.get("current_session_catchup_unchanged_count") or 0)
    for item in warm_symbols.values()
)

daily_summary = heartbeat.get("daily_history") or {}
assert daily_summary.get("status") == "PASS"
assert daily_summary.get("path") == daily_path
assert int(daily_summary.get("required_rows") or 0) == 120
assert daily_summary.get("same_opend_context_required") is True
assert daily_summary.get("historical_query") is True
assert daily_summary.get("currentness_proven") is False
assert daily_summary.get("bar_closure_promotion_authorized") is False
assert daily_summary.get("radar_admission") == "BLOCKED"
assert daily_summary.get("live_trade") is False
daily_summary_symbols = daily_summary.get("symbols") or {}
assert set(daily_summary_symbols) == expected_symbols
for symbol, item in daily_summary_symbols.items():
    assert item.get("status") == "PASS"
    assert int(item.get("row_count") or 0) == 120
    assert item.get("latest_date")

assert daily.get("schema") == "stock_razor_futu_us_daily_history_v1"
assert daily.get("repo_sha") == expected_sha
assert daily.get("runtime_instance_id") == heartbeat.get("runtime_instance_id")
assert daily.get("status") == "PASS"
assert int(daily.get("required_rows") or 0) == 120
assert daily.get("same_opend_context_required") is True
assert daily.get("historical_query") is True
assert daily.get("currentness_proven") is False
assert daily.get("bar_closure_promotion_authorized") is False
assert daily.get("research_only") is True
assert daily.get("can_confirm_signal") is False
assert daily.get("radar_admission") == "BLOCKED"
assert daily.get("live_trade") is False
daily_symbols = daily.get("symbols") or {}
assert set(daily_symbols) == expected_symbols
for symbol, item in daily_symbols.items():
    assert item.get("status") == "PASS"
    assert int(item.get("row_count") or 0) == 120
    assert len(item.get("rows") or []) == 120
    assert item.get("completed_prior_session_only") is True
    assert item.get("historical_query") is True
    assert item.get("currentness_proven") is False
    assert item.get("bar_closure_promotion_authorized") is False
    assert item.get("radar_admission") == "BLOCKED"
    assert item.get("live_trade") is False

canonical_cache = heartbeat.get("canonical_cache") or {}
assert set(canonical_cache) == expected_symbols
for symbol in expected_symbols:
    item = canonical_cache.get(symbol) or {}
    assert int(item.get("bar_count") or 0) >= 1170
    assert int(item.get("bar_count_5m") or 0) >= 234
    assert int(item.get("bar_count_15m") or 0) >= 78
    assert int(item.get("bar_count_1h") or 0) >= 20

snapshot_symbols = snapshot.get("symbols") or {}
assert set(snapshot_symbols) == expected_symbols
for symbol in expected_symbols:
    frames = (snapshot_symbols.get(symbol) or {}).get("timeframes") or {}
    assert len(frames.get("1m") or []) >= 1170
    assert len(frames.get("5m") or []) >= 234
    assert len(frames.get("15m") or []) >= 78
    assert len(frames.get("1h") or []) >= 20

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
    and heartbeat.get("intraday_closure_15m_60m_summary") == "PASS"
    else "UNPROVEN"
)
assert heartbeat.get("bar_closure_evidence_state") == expected_bar_closure
assert heartbeat.get("bar_closure") == expected_bar_closure
intraday = heartbeat.get("intraday_closure_15m_60m") or {}
assert set(intraday) == expected_symbols
assert heartbeat.get("intraday_closure_15m_60m_summary") in {"UNKNOWN", "PASS"}
for item in intraday.values():
    assert item.get("status") in {"UNKNOWN", "PASS"}
    assert item.get("bar_closure_promotion_authorized") is False
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
      echo "OPEND_CANDIDATE_PREVIEW=READONLY_PASS"
      if [[ "$expected_ab_blend" == "1" ]]; then
        echo "AB_BLEND_OPEND_SUBSCRIPTIONS=PASS"
      else
        echo "AB_BLEND_OPEND_SUBSCRIPTIONS=DISABLED"
      fi
      exit 0
    fi
  fi
  sleep 5
done
echo US_OPEND_LIVEFEED_ACCEPTANCE_TIMEOUT >&2
exit 1
