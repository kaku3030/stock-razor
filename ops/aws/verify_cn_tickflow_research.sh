#!/usr/bin/env bash
set -euo pipefail

expected_worker_sha="${1:?expected worker sha required}"
[[ "$expected_worker_sha" =~ ^[0-9a-f]{40}$ ]]
service="stock-razor-cn-tickflow-research.service"
status="/run/stock-razor-cn-tickflow/latest-research-observation.json"
python_bin="/opt/stock-razor-cn-tickflow/venv/bin/python"

for _ in $(seq 1 24); do
  if systemctl is-active --quiet "$service" && [[ -s "$status" ]]; then
    if "$python_bin" - "$status" "$expected_worker_sha" <<'PY'
import json
import re
import sys

path, expected = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
assert payload.get("schema") == "stock_razor_cn_tickflow_research_observation_v0_1"
assert payload.get("repo_sha") == expected
assert re.fullmatch(r"[0-9a-f]{40}", payload["repo_sha"])
assert payload.get("provider") == "TICKFLOW_PREMIUM"
assert payload.get("status") == "PASS_RESEARCH_ONLY"
assert isinstance(payload.get("symbols"), dict) and payload["symbols"]
assert type(payload.get("sequence")) is int and payload["sequence"] > 0
assert not payload.get("failure_class")
assert payload.get("research_only") is True
assert payload.get("source_arbiter_admission") == "BLOCKED"
assert payload.get("radar_admission") == "BLOCKED"
assert payload.get("live_trade") is False
assert payload.get("canonical_write_authorized") is False
print("CN_TICKFLOW_WORKER_REPO_SHA=" + payload["repo_sha"])
print("CN_TICKFLOW_SOURCE_REPO_SHA=" + payload["repo_sha"])
print("CN_TICKFLOW_PROVIDER=TICKFLOW_PREMIUM")
print("CN_TICKFLOW_PROVIDER_QUALIFICATION=NOT_VERIFIED")
PY
    then
      systemctl is-enabled "$service" >/dev/null
      echo "CN_TICKFLOW_WORKER_VERIFY=PASS"
      echo "SOURCE_ARBITER_ADMISSION=BLOCKED"
      echo "RADAR_ADMISSION=BLOCKED"
      echo "LIVE_TRADE=NO"
      exit 0
    fi
  fi
  sleep 5
done

echo "CN_TICKFLOW_WORKER_VERIFY=BLOCKED" >&2
exit 1
