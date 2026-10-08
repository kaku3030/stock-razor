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
            "US.AMD": {"counts": {"15m": 22}, "latest": {"close": "PRICE_SENTINEL_AMD"}},
            "US.NVDA": {"counts": {"15m": 23}, "latest": {"close": "PRICE_SENTINEL_NVDA"}},
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
            "rows": [{"close": "PRICE_SENTINEL_CN_A"}],
            "api_key": "SECRET_DO_NOT_PRINT",
        },
        "518880": {
            "status": "PASS", "sequence": 23, "provider_used": "eastmoney",
            "provider_request_latency_ms": 80.0,
            "source_age_seconds": age,
            "emitted_at_utc": (NOW - timedelta(seconds=age)).isoformat(),
            "total_row_count": 150, "currentness": "PROVEN",
            "rows": [{"close": "PRICE_SENTINEL_CN_B"}],
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
    for secret in ("SECRET_DO_NOT_PRINT", "\"close\"", "PRICE_SENTINEL_"):
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



def test_us_heartbeat_versus_accepted_events_are_separate_observations():
    from scripts.probe_cloud_source_arbiter_shadow import (
        _sample_progress_evidence, observe_source_progress,
    )
    before = _sample_progress_evidence(
        us_health={
            "status": "HEALTHY", "market_state_us": "OPEN",
            "sequence": 10, "event_count": 100, "accepted_event_count": 90,
        },
        us_snapshot={"sequence": 20},
        cn_reads=cn_rows(),
    )
    after_cn = cn_rows()
    after_cn["159611"]["sequence"] = 24
    after_cn["159611"]["rows"] = [{"label": "2026-10-08 15:00", "close": "PRIVATE_BAR"}]
    after = _sample_progress_evidence(
        us_health={
            "status": "HEALTHY", "market_state_us": "OPEN",
            "sequence": 11, "event_count": 102, "accepted_event_count": 91,
        },
        us_snapshot={"sequence": 21},
        cn_reads=after_cn,
    )
    result = observe_source_progress(before, after, interval_seconds=12.1)
    assert result["us"]["heartbeat_sequence"] == "ADVANCED"
    assert result["us"]["received_event_counter"] == "ADVANCED"
    assert result["us"]["accepted_event_counter"] == "ADVANCED"
    assert result["us"]["event_progress_classification"] == "ACCEPTED_COUNTER_ADVANCED_UNQUALIFIED"
    assert result["cn"]["159611"]["observer_poll_sequence"] == "ADVANCED"
    assert result["cn"]["159611"]["15m_last_bar_label"] == "UNKNOWN"
    assert result["cn"]["159611"]["provider_event_progress"] == "NOT_VERIFIED"
    assert result["unique_provider_event_delivery_qualified"] is False
    assert "PRIVATE_BAR" not in json.dumps(result)
    assert result["radar_admission"] == "BLOCKED"


def test_closed_market_no_event_change_is_not_false_outage():
    from scripts.probe_cloud_source_arbiter_shadow import (
        _sample_progress_evidence, observe_source_progress,
    )
    closed = _sample_progress_evidence(
        us_health={
            "status":"HEALTHY", "market_state_us":"CLOSED",
            "sequence":10, "event_count":100, "accepted_event_count":90,
        },
        us_snapshot={"sequence":40},
        cn_reads=cn_rows(),
    )
    later = _sample_progress_evidence(
        us_health={
            "status":"HEALTHY", "market_state_us":"CLOSED",
            "sequence":12, "event_count":100, "accepted_event_count":90,
        },
        us_snapshot={"sequence":40},
        cn_reads=cn_rows(),
    )
    result=observe_source_progress(closed,later,interval_seconds=12)
    assert result["us"]["heartbeat_sequence"] == "ADVANCED"
    assert result["us"]["accepted_event_counter"] == "UNCHANGED"
    assert result["us"]["event_progress_classification"] == "CLOSED_SESSION_NO_ADVANCEMENT_NOT_FAILURE"
    assert result["us"]["canonical_snapshot_sequence"] == "UNCHANGED"
    assert result["cn"]["518880"]["observer_poll_sequence"] == "UNCHANGED"
    assert result["unique_provider_event_delivery_qualified"] is False


def test_counter_reset_and_missing_are_never_positive_feed_progress():
    from scripts.probe_cloud_source_arbiter_shadow import (
        observe_source_progress,
    )
    a={"us":{"market_state":"OPEN", "heartbeat_sequence":10, "accepted_events":9,
             "received_events":10,"canonical_sequence":4},
       "cn":{"159611":{"poll_sequence":10,"last_bar_label":"2026-10-08 10:00","reported_provider":"tencent"},
             "518880":{"poll_sequence":3,"last_bar_label":None,"reported_provider":"eastmoney"}}}
    b={"us":{"market_state":"OPEN", "heartbeat_sequence":11, "accepted_events":1,
             "received_events":9,"canonical_sequence":None},
       "cn":{"159611":{"poll_sequence":11,"last_bar_label":"2026-10-08 10:15","reported_provider":"tencent"},
             "518880":{"poll_sequence":4,"last_bar_label":None,"reported_provider":"tencent"}}}
    r=observe_source_progress(a,b,interval_seconds=12)
    assert r["us"]["accepted_event_counter"]=="COUNTER_RESET_OR_REORDERED"
    assert r["us"]["canonical_snapshot_sequence"]=="UNKNOWN"
    assert r["us"]["event_progress_classification"]=="COUNTER_RESET_OR_REORDERED"
    assert r["cn"]["159611"]["15m_last_bar_label"]=="CHANGED_UNQUALIFIED"
    assert r["cn"]["518880"]["15m_last_bar_label"]=="SOURCE_SWITCH_UNQUALIFIED"
    assert r["cloud_off_pc_independence"]=="NOT_VERIFIED"
    assert r["live_trade"] is False


def test_invalid_progress_interval_is_not_silent_pass():
    import pytest
    from scripts.probe_cloud_source_arbiter_shadow import observe_source_progress
    for invalid in (0,-1,31,True):
        with pytest.raises(ValueError):
            observe_source_progress({}, {}, interval_seconds=invalid)



def test_futu_market_session_mapping_is_reused_in_aws_shadow():
    from scripts.probe_cloud_source_arbiter_shadow import (
        _sample_progress_evidence, observe_source_progress,
    )

    for market_state, session, expected_progress in (
        ("MORNING", "regular", "EVENT_PROGRESS_NOT_VERIFIED"),
        ("AFTERNOON", "regular", "EVENT_PROGRESS_NOT_VERIFIED"),
        ("PRE_MARKET_BEGIN", "premarket", "NON_REGULAR_SESSION_NO_ADVANCEMENT_NOT_FAILURE"),
        ("AFTER_HOURS_END", "afterhours", "NON_REGULAR_SESSION_NO_ADVANCEMENT_NOT_FAILURE"),
        ("OVERNIGHT", "overnight", "NON_REGULAR_SESSION_NO_ADVANCEMENT_NOT_FAILURE"),
        ("WAITING_OPEN", "closed", "CLOSED_SESSION_NO_ADVANCEMENT_NOT_FAILURE"),
        ("CLOSED", "closed", "CLOSED_SESSION_NO_ADVANCEMENT_NOT_FAILURE"),
        ("OPEN", "unknown", "EVENT_PROGRESS_NOT_VERIFIED"),
        ("arbitrary-secret-state", "unknown", "EVENT_PROGRESS_NOT_VERIFIED"),
    ):
        cache = _sample_progress_evidence(
            us_health={
                "status": "HEALTHY", "market_state_us": market_state,
                "sequence": 5, "event_count": 6, "accepted_event_count": 4,
            },
            us_snapshot={"status": "STALE", "sequence": 2, "source_age_seconds": 350},
            cn_reads=cn_rows(),
        )
        assert cache["us"]["market_session"] == session
        if session == "unknown":
            assert cache["us"]["market_state"] == "UNKNOWN"
        result = observe_source_progress(cache, cache, interval_seconds=12)
        assert result["us"]["event_progress_classification"] == expected_progress
        assert result["us"]["canonical_snapshot_status"] == "STALE"
        assert result["us"]["canonical_snapshot_age_seconds"] == 350
        assert result["us"]["canonical_chain_classification"] == "EXPORT_NOT_CONFIRMED"
        assert result["unique_provider_event_delivery_qualified"] is False


def test_export_pass_but_stale_snapshot_does_not_blame_provider():
    from scripts.probe_cloud_source_arbiter_shadow import (
        _sample_progress_evidence, observe_source_progress,
    )
    health = {
        "status": "HEALTHY", "market_state_us": "PRE_MARKET_BEGIN",
        "sequence": 12, "event_count": 10, "accepted_event_count": 10,
        "canonical_export_status": "PASS", "api_key": "NEVER_EXPOSE",
    }
    snapshot = {
        "status": "STALE", "sequence": 40, "source_age_seconds": 634,
        "symbols": {"US.AMD": {"latest": {"close": "PRICE_SECRET"}}},
    }
    first = _sample_progress_evidence(
        us_health=health, us_snapshot=snapshot, cn_reads=cn_rows(),
    )
    second = _sample_progress_evidence(
        us_health={**health, "sequence": 13},
        us_snapshot=snapshot, cn_reads=cn_rows(),
    )
    result = observe_source_progress(first, second, interval_seconds=12.2)
    assert result["us"]["heartbeat_sequence"] == "ADVANCED"
    assert result["us"]["market_state"] == "PRE_MARKET_BEGIN"
    assert result["us"]["market_session"] == "premarket"
    assert result["us"]["event_progress_classification"] == (
        "NON_REGULAR_SESSION_NO_ADVANCEMENT_NOT_FAILURE"
    )
    assert result["us"]["canonical_chain_classification"] == (
        "EXPORT_PASS_SNAPSHOT_STALE_CAUSE_UNKNOWN"
    )
    assert "NEVER_EXPOSE" not in json.dumps(result)
    assert "PRICE_SECRET" not in json.dumps(result)
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_accepted_callbacks_without_snapshot_sequence_change_not_promoted():
    from scripts.probe_cloud_source_arbiter_shadow import (
        _sample_progress_evidence, observe_source_progress,
    )
    def sample(accepted, sequence):
        return _sample_progress_evidence(
            us_health={
                "status": "HEALTHY", "market_state_us": "MORNING",
                "sequence": 9, "event_count": accepted + 1,
                "accepted_event_count": accepted, "canonical_export_status": "PASS",
            },
            us_snapshot={
                "status": "PASS", "sequence": sequence,
                "source_age_seconds": float("nan"),
            },
            cn_reads=cn_rows(),
        )

    result = observe_source_progress(
        sample(10, 4), sample(11, 4), interval_seconds=12,
    )
    assert result["us"]["accepted_event_counter"] == "ADVANCED"
    assert result["us"]["market_session"] == "regular"
    assert result["us"]["canonical_snapshot_age_seconds"] is None
    assert result["us"]["canonical_chain_classification"] == (
        "ACCEPTED_CALLBACKS_SNAPSHOT_UNCHANGED_CAUSE_UNKNOWN"
    )
    assert result["us"]["event_progress_classification"] == (
        "ACCEPTED_COUNTER_ADVANCED_UNQUALIFIED"
    )
    assert result["unique_provider_event_delivery_qualified"] is False
