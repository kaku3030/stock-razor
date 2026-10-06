#!/usr/bin/env bash
set -euo pipefail
expected_sha="${1:?expected sha required}"
status=/run/stock-razor-us-livefeed/latest-heartbeat.json
for _ in $(seq 1 18); do
  if systemctl is-active --quiet stock-razor-us-livefeed.service && [[ -s "$status" ]]; then
    hb=$(cat "$status")
    if grep -q "\"repo_sha\":\"$expected_sha\"" <<<"$hb" && grep -Eq '"event_count":[1-9][0-9]*' <<<"$hb"; then
      systemctl is-enabled stock-razor-us-livefeed.service
      systemctl is-active stock-razor-us-livefeed.service
      cat "$status"
      exit 0
    fi
  fi
  sleep 5
done
echo US_OPEND_LIVEFEED_ACCEPTANCE_TIMEOUT >&2
exit 1
