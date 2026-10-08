"""Cloud Source Arbiter dry-run observer never upgrades live authority."""
from datetime import datetime, timedelta, timezone
import json

from scripts.probe_cloud_source_arbiter_shadow import audit_cloud_shadow


NOW = datetime(2026, 10, 8, 9, 20, tzinfo=timezone.utc)


def us_health(state="HEALTHY"):
    return {
        "status": state, "provider_callback_latency_ms": 0.01,
        "controller_lifecycle": "CONNECTED", "raw_key": "SECRET_DO_NOT_PRINT",
    }


def us_snapshot(*, status="PASS", age=7):
    return {
        "status": status, "sequence": 42,
        "source_age_seconds": age,
        "emitted_at_utc": (NOW - timedelta(seconds=age)).isoformat(),
        "symbols": {
            "US.AMD": {"counts": {"15m": 22}, "latest": {"close": 999}},
            "US.NVDA": {"counts": {"15m": 23}, "latest": {"close": 888}},
        },
        "user_account": "SECRET_DO_NOT_PRINT",
    }


def cn_rows(*, age=9):
    return {
        "159611": {
            "status": "PASS", "sequence": 23, "provider_used": "tencent",
            "provider_request_latency_ms": 35.4,
            "source_age_seconds": age,
            "emitted_at_utc": (NOW - timedelta(seconds=age)).isoformat(),
            "total_row_count": 64, "currentness": "PROVEN",
            "rows": [{"close": 222}],
            "api_key": "SECRET_DO_NOT_PRINT",
        },
        "518880": {
            "status": "PASS", "sequence": 23, "provider_used": "eastmoney",
            "provider_request_latency_ms": 80.0,
            "source_age_seconds": age,
            "emitted_at_utc": (NOW - timedelta(seconds=age)).isoformat(),
            "total_row_count": 150, "currentness": "PROVEN",
            "rows": [{"close": 111}],
        },
    }


def test_realistic_cloud_health_never_implies_qualified_canonical_writer():
    d=audit_cloud_shadow(us_health=us_health(), us_snapshot=us_snapshot(),
                         cn_reads=cn_rows(), now=NOW)
    assert d["schema"] == "stock_razor_data_fabric_aws_shadow_witness_v0_1"
    assert len(d["entries"]) == 4
    assert d["sources_proven_qualified"] == 0
    assert d["source_arbiter_runtime_admission"] == "BLOCKED"
    assert d["off_pc_independent_market_acquisition"] == "NOT_VERIFIED"
    assert d["canonical_writer_created"] is False
    assert d["can_confirm_signal"] is False
    for entry in d["entries"]:
        proposal = entry["decision"]
        assert proposal["decision"] == "BLOCKED"
        assert proposal["proposed_source"] is None
        assert proposal["single_writer_lease_acquired"] is False
        assert proposal["canonical_write_authorized"] is False
        assert "entitlement_qualified" in next(iter(proposal["rejected_source_reasons"].values()))

    assert d["entries"][0]["reported_source"] == "CLOUD_OPEND"
    assert d["entries"][2]["reported_source"] == "TENCENT"
    assert d["entries"][3]["reported_source"] == "EASTMONEY"
    assert d["entries"][0]["observed_bar_count"] == 22
    assert d["entries"][2]["observed_bar_count"] == 64
    assert d["entries"][2]["decision"]["source_latency_ms"] is None
    payload=json.dumps(d)
    for secret in ("SECRET_DO_NOT_PRINT", "close", "999", "888", "222", "111"):
        assert secret not in payload


def test_stale_and_unknown_data_remain_explicit_rejected_evidence():
    snapshot=us_snapshot(status="STALE", age=600)
    rows=cn_rows()
    rows["159611"].update(
        provider_used="mystery-api", emitted_at_utc="bad-timestamp",
        provider_request_latency_ms=float("nan"), sequence=True,
        total_row_count=-30
    )
    rows["518880"].update(
        status="STALE", source_age_seconds=250, sequence=None,
        emitted_at_utc="untrusted"
    )
    d=audit_cloud_shadow(us_health=us_health("DEGRADED"),
                         us_snapshot=snapshot, cn_reads=rows, now=NOW)
    assert d["us_livefeed_health"] == "DEGRADED"
    assert d["entries"][0]["read_status"] == "STALE"
    assert d["entries"][0]["decision"]["decision"] == "BLOCKED"
    assert "SOURCE_AGE_OVER_LIMIT" in d["entries"][0]["decision"]["rejected_source_reasons"]["CLOUD_OPEND"]
    assert d["entries"][2]["reported_source"] == "UNKNOWN"
    assert d["entries"][2]["observed_bar_count"] is None
    assert d["entries"][2]["decision"]["rejected_source_reasons"] == {}
    assert d["entries"][3]["decision"]["decision"] == "BLOCKED"
    assert "STALE_QUALIFICATION_EVIDENCE" in d["entries"][3]["decision"]["rejected_source_reasons"]["EASTMONEY"]


def test_wrong_market_provider_and_no_data_never_invent_success():
    d=audit_cloud_shadow(
        us_health={"status":"SUPER_OK"},
        us_snapshot={"status":"INVALID", "symbols": {"US.AMD": {"counts": {"15m": True}}}},
        cn_reads={"159611": {"provider_used": "US.AMD", "status": "NO_DATA"}},
        now=NOW,
    )
    assert d["us_livefeed_health"] == "UNKNOWN"
    assert d["entries"][0]["observed_bar_count"] is None
    assert d["entries"][1]["observed_bar_count"] is None
    assert d["entries"][2]["reported_source"] == "UNKNOWN"
    assert d["entries"][3]["reported_source"] == "UNKNOWN"
    assert all(x["decision"]["decision"] == "BLOCKED" for x in d["entries"])
