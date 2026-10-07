#!/usr/bin/env bash
set -euo pipefail

expected_sha="${1:?expected collector sha required}"
require_snapshot="${REQUIRE_SNAPSHOT:-true}"
service="stock-razor-us-options-intelligence.service"
status="/run/stock-razor-us-options-intelligence/latest-heartbeat.json"
snapshot="/run/stock-razor-us-options-intelligence/options-intelligence.json"
python_bin="/opt/stock-razor-us-options-intelligence/venv/bin/python"

case "$require_snapshot" in
  (true|false) ;;
  (*) echo "REQUIRE_SNAPSHOT must be true or false" >&2; exit 2;;
esac

for _ in $(seq 1 30); do
  if systemctl is-active --quiet "$service" && [[ -s "$status" ]]; then
    if "$python_bin" - "$status" "$snapshot" "$expected_sha" "$require_snapshot" <<'PY'
import json
import os
import sys

status_path, snapshot_path, expected_sha, require_snapshot = sys.argv[1:]
with open(status_path, encoding="utf-8") as handle:
    heartbeat = json.load(handle)

assert heartbeat.get("type") == "us_options_intelligence_heartbeat"
assert heartbeat.get("repo_sha") == expected_sha
assert int(heartbeat.get("sequence") or 0) > 0
assert heartbeat.get("opend_host") == "127.0.0.1"
assert int(heartbeat.get("opend_port") or 0) == 11111
assert heartbeat.get("research_only") is True
assert heartbeat.get("trading_authority") is False
assert heartbeat.get("live_trade") is False
symbols = heartbeat.get("symbols") or []
assert symbols == ["US.QQQ"]

cycle = heartbeat.get("cycle") or {}
assert cycle.get("status") in {"PASS_RESEARCH", "DEGRADED_RESEARCH", "BLOCKED"}
assert int(cycle.get("sequence") or 0) > 0
assert cycle.get("research_only") is True
assert cycle.get("trading_authority") is False
assert cycle.get("live_trade") is False
assert cycle.get("phase") in {
    "premarket", "intraday", "postmarket", "non_trading", "unknown"
}

snapshot_written = cycle.get("snapshot_written") is True
if require_snapshot == "true":
    assert snapshot_written is True
    assert cycle.get("status") in {"PASS_RESEARCH", "DEGRADED_RESEARCH"}
    assert int(cycle.get("packets_written") or 0) >= 1
else:
    if not snapshot_written:
        assert cycle.get("status") == "BLOCKED"
        assert cycle.get("phase") in {"postmarket", "non_trading", "unknown"}

if snapshot_written:
    assert os.path.isfile(snapshot_path) and os.path.getsize(snapshot_path) > 0
    with open(snapshot_path, encoding="utf-8") as handle:
        snapshot = json.load(handle)

    assert snapshot.get("schema") == "stock_razor_us_options_intelligence_snapshot_v1"
    assert snapshot.get("repo_sha") == expected_sha
    assert int(snapshot.get("sequence") or 0) > 0
    assert snapshot.get("research_only") is True
    assert snapshot.get("trading_authority") is False
    assert snapshot.get("live_trade") is False
    option_symbols = snapshot.get("symbols") or {}
    assert set(option_symbols) == {"US.QQQ"}

    packet = option_symbols["US.QQQ"]
    assert packet.get("underlying_symbol") == "QQQ"
    assert packet.get("context_permission") in {"RESEARCH_ONLY", "DEGRADED_RESEARCH"}
    assert packet.get("radar_admission") == "CONTEXT_ONLY"
    assert packet.get("decision_permission") == "BLOCKED_V0_1"
    assert packet.get("price_acceptance_required") is True
    assert packet.get("trading_authority") is False
    assert packet.get("live_trade") is False

    current = packet.get("current_gex") or {}
    assert current.get("research_only") is True
    assert current.get("trading_authority") is False
    assert float(current.get("completeness") or 0) > 0
    assert current.get("spot_source") in {"previous_regular_close", "regular_last"}
    assert current.get("spot_asof")

    freshness = packet.get("freshness") or {}
    assert freshness.get("status") in {"PASS_RESEARCH", "DEGRADED"}
    assert int(freshness.get("usable") or 0) > 0
    assert float(freshness.get("completeness") or 0) > 0

    clock = packet.get("clock_alignment") or {}
    assert clock.get("status") in {"PASS_RESEARCH", "DEGRADED"}
    assert clock.get("underlying_asof")
    assert clock.get("quote_asof_max")
PY
    then
      systemctl is-enabled "$service"
      systemctl is-active "$service"
      test "$(systemctl show "$service" -p NoNewPrivileges --value)" = "yes"
      test "$(systemctl show "$service" -p ProtectSystem --value)" = "strict"
      test "$(systemctl show "$service" -p ProtectHome --value)" = "yes"
      cat "$status"
      printf '\n'
      echo "US_OPTIONS_INTELLIGENCE_VERIFY=PASS"
      echo "RESEARCH_ONLY=YES"
      echo "RADAR_ADMISSION=CONTEXT_ONLY"
      echo "LIVE_TRADE=NO"
      exit 0
    fi
  fi
  sleep 5
done

echo US_OPTIONS_INTELLIGENCE_ACCEPTANCE_TIMEOUT >&2
systemctl status "$service" --no-pager >&2 || true
journalctl -u "$service" -n 100 --no-pager >&2 || true
exit 1
