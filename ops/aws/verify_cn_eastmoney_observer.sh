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
assert payload.get("provider_policy") == "EASTMONEY_PRIMARY_TENCENT_FALLBACK"
assert set(payload.get("provider_lineages") or []) == {"eastmoney", "tencent"}
assert isinstance(payload.get("intraday_timestamp_semantics_proven"), bool)
assert isinstance(payload.get("intraday_currentness_proven"), bool)
assert payload.get("research_only") is True
assert payload.get("can_confirm_signal") is False
assert payload.get("radar_admission") == "BLOCKED"
assert payload.get("live_trade") is False
assert payload.get("status") == "PASS"

symbols = payload.get("symbols") or {}
assert symbols
for symbol, item in symbols.items():
    assert item.get("status") == "PASS"
    assert item.get("provider_policy") == "EASTMONEY_PRIMARY_TENCENT_FALLBACK"
    assert item.get("radar_admission") == "BLOCKED"
    assert item.get("live_trade") is False
    frames = item.get("timeframes") or {}
    assert set(frames) == {"1d", "60m", "15m"}
    for timeframe in ("1d", "60m", "15m"):
        frame = frames[timeframe]
        assert frame.get("status") == "PASS"
        assert int(frame.get("row_count") or 0) > 0
        if timeframe == "1d":
            assert frame.get("currentness") == "UNPROVEN"
            assert frame.get("currentness_qualification") is None
        else:
            assert frame.get("currentness") in {"UNPROVEN", "PROVEN"}
        rows = frame.get("rows") or []
        assert rows
        provider = frame.get("provider_used")
        lineage = frame.get("provider_lineage")
        assert provider in {"eastmoney", "tencent"}
        assert lineage == provider
        latest = rows[-1]
        assert latest.get("provider") == provider
        if provider == "eastmoney":
            assert latest.get("volume_unit") == "PROVIDER_RAW_UNVERIFIED"
            assert frame.get("fallback_from") is None
        else:
            assert latest.get("volume_unit") == "HAND"
            assert frame.get("fallback_from") == "eastmoney"
            assert frame.get("fallback_reason")
    assert frames["1d"].get("timestamp_semantic") == "DAILY_DATE"
    intraday_proven = True
    for timeframe in ("60m", "15m"):
        frame = frames[timeframe]
        if frame.get("provider_used") == "tencent":
            qualification = frame.get("timestamp_qualification") or {}
            assert qualification.get("status") == "PASS"
            assert qualification.get("timestamp_semantic") == "BAR_END"
            assert qualification.get("currentness_proven") is False
            assert qualification.get("continuity_proven") is False
            assert qualification.get("radar_admission") == "BLOCKED"
            assert qualification.get("live_trade") is False
            assert frame.get("timestamp_semantic") == "BAR_END"
            currentness = frame.get("currentness_qualification") or {}
            assert currentness.get("timestamp_semantic") == "BAR_END"
            assert currentness.get("continuity_proven") is False
            assert currentness.get("radar_admission") == "BLOCKED"
            assert currentness.get("live_trade") is False
            if frame.get("currentness") == "PROVEN":
                assert currentness.get("status") == "PASS"
                assert currentness.get("currentness_proven") is True
            else:
                assert currentness.get("status") == "BLOCKED"
                assert currentness.get("currentness_proven") is False
        else:
            intraday_proven = False
            assert frame.get("timestamp_semantic") == "UNKNOWN"
            assert frame.get("timestamp_qualification") is None
            assert frame.get("currentness") == "UNPROVEN"
            assert frame.get("currentness_qualification") is None
    assert item.get("intraday_timestamp_semantics_proven") is intraday_proven
    item_currentness = all(
        frames[timeframe].get("currentness") == "PROVEN"
        for timeframe in ("60m", "15m")
    )
    assert item.get("intraday_currentness_proven") is item_currentness

assert payload.get("intraday_timestamp_semantics_proven") is all(
    item.get("intraday_timestamp_semantics_proven") is True
    for item in symbols.values()
)
assert payload.get("intraday_currentness_proven") is all(
    item.get("intraday_currentness_proven") is True
    for item in symbols.values()
)

summary = {
    "schema": payload.get("schema"),
    "repo_sha": payload.get("repo_sha"),
    "status": payload.get("status"),
    "provider_policy": payload.get("provider_policy"),
    "provider_lineages": payload.get("provider_lineages"),
    "intraday_timestamp_semantics_proven": payload.get("intraday_timestamp_semantics_proven"),
    "intraday_currentness_proven": payload.get("intraday_currentness_proven"),
    "radar_admission": payload.get("radar_admission"),
    "live_trade": payload.get("live_trade"),
    "symbols": {
        symbol: {
            "status": item.get("status"),
            "providers_used": item.get("providers_used"),
            "timeframes": {
                timeframe: {
                    "status": frame.get("status"),
                    "provider_used": frame.get("provider_used"),
                    "provider_lineage": frame.get("provider_lineage"),
                    "row_count": frame.get("row_count"),
                    "timestamp_semantic": frame.get("timestamp_semantic"),
                    "timestamp_qualification_status": (
                        (frame.get("timestamp_qualification") or {}).get("status")
                    ),
                    "currentness_qualification_status": (
                        (frame.get("currentness_qualification") or {}).get("status")
                    ),
                    "currentness": frame.get("currentness"),
                    "fallback_from": frame.get("fallback_from"),
                    "latest_label": ((frame.get("rows") or [{}])[-1]).get("label"),
                }
                for timeframe, frame in (item.get("timeframes") or {}).items()
            },
        }
        for symbol, item in symbols.items()
    },
}
print("CN_EASTMONEY_COMPACT=" + json.dumps(summary, separators=(",", ":"), sort_keys=True))
PY
    then
      systemctl is-enabled "$service"
      systemctl is-active "$service"
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
