from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.services.data_fabric_source_arbiter_policy import (
    Candidate,
    propose_authoritative_source,
)


NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
GATES = {
    "reachable": "PASS",
    "process_healthy": "PASS",
    "entitlement_qualified": "PASS",
    "freshness_qualified": "PASS",
    "continuity_qualified": "PASS",
    "completeness_qualified": "PASS",
    "correctness_qualified": "PASS",
    "source_progress_qualified": "PASS",
}


def source(origin="CLOUD_OPEND", *, market="US", symbol="US.AMD", timeframe="1m", latency=12, **kw):
    args = dict(
        source=origin, market=market, symbol=symbol, timeframe=timeframe,
        latency_ms=latency, source_age_ms=200, sequence=15,
        observed_at_utc=NOW, **GATES,
    )
    args.update(kw)
    return Candidate(**args)


def decide(*candidates, market="US", symbol="US.AMD", timeframe="1m", **kwargs):
    return propose_authoritative_source(
        market, symbol, timeframe, candidates, now_utc=NOW,
        max_age_ms=1500, **kwargs
    )


def test_us_fastest_qualified_desktop_selected_but_no_canonical_writer():
    cloud=source(latency=12)
    desktop=source("DESKTOP_OPEND", latency=5, sequence=16)
    d=decide(cloud, desktop, incumbent="CLOUD_OPEND")
    assert d["decision"] == "SHADOW_PROPOSAL"
    assert d["proposed_source"] == "DESKTOP_OPEND"
    assert d["switch_reason"] == "FASTER_QUALIFIED_SOURCE"
    assert d["qualified_candidate_count"] == 2
    assert d["source_sequence"] == 16
    assert d["single_writer_lease_acquired"] is False
    assert d["canonical_write_authorized"] is False
    assert d["radar_admission"] == "BLOCKED"
    assert d["can_confirm_signal"] is False
    assert d["live_trade"] is False


def test_desktop_offline_cloud_warm_takeover_proposed_only():
    broken=source("DESKTOP_OPEND", latency=1, reachable="FAIL")
    cloud=source("CLOUD_OPEND", latency=14)
    d=decide(broken, cloud, incumbent="DESKTOP_OPEND")
    assert d["proposed_source"] == "CLOUD_OPEND"
    assert d["switch_reason"] == "INCUMBENT_NOT_QUALIFIED"
    assert d["rejected_source_reasons"]["DESKTOP_OPEND"] == ["reachable"]
    assert d["data_qualification"] == "NOT_VERIFIED"


def test_unknown_entitlement_never_qualifies_even_if_fastest():
    unqualified=source("DESKTOP_OPEND", latency=1, entitlement_qualified="UNKNOWN")
    fallback=source("ALPACA_IEX", latency=30)
    d=decide(unqualified, fallback)
    assert d["proposed_source"] == "ALPACA_IEX"
    assert "entitlement_qualified" in d["rejected_source_reasons"]["DESKTOP_OPEND"]


def test_free_cn_provider_never_admitted_without_independent_evidence():
    tick=source("CLOUD_TICKFLOW", market="CN", symbol="159611", timeframe="15m",
                latency=1, entitlement_qualified="UNKNOWN")
    backup=source("TENCENT", market="CN", symbol="159611", timeframe="15m",
                  latency=80)
    d=decide(tick, backup, market="CN", symbol="159611", timeframe="15m")
    assert d["proposed_source"] == "TENCENT"
    assert d["qualified_candidate_count"] == 1
    assert d["radar_admission"] == "BLOCKED"


def test_all_unknown_results_in_blocked_and_no_writer():
    candidate=source(latency=2, freshness_qualified="UNKNOWN")
    d=decide(candidate)
    assert d["decision"] == "BLOCKED"
    assert d["proposed_source"] is None
    assert d["source_latency_ms"] is None
    assert d["switch_reason"] == "NO_QUALIFIED_SOURCE"


def test_timestamp_stale_future_and_missing_latency_block():
    older=source(observed_at_utc=NOW-timedelta(minutes=10))
    future=source("DESKTOP_OPEND", observed_at_utc=NOW+timedelta(seconds=2))
    missing=source("ALPACA_IEX", latency=None)
    d=decide(older, future, missing)
    assert d["decision"] == "BLOCKED"
    assert "STALE_QUALIFICATION_EVIDENCE" in d["rejected_source_reasons"]["CLOUD_OPEND"]
    assert "FUTURE_OBSERVATION" in d["rejected_source_reasons"]["DESKTOP_OPEND"]
    assert "MEASURED_LATENCY_UNAVAILABLE" in d["rejected_source_reasons"]["ALPACA_IEX"]


def test_intraday_age_fails_even_with_stated_freshness_pass():
    delayed=source(source_age_ms=3000, freshness_qualified="PASS")
    d=decide(delayed)
    assert d["decision"] == "BLOCKED"
    assert "SOURCE_AGE_OVER_LIMIT" in d["rejected_source_reasons"]["CLOUD_OPEND"]


def test_anti_flap_holds_already_qualified_source():
    incumbent=source(latency=10)
    competitor=source("DESKTOP_OPEND", latency=8)
    d=decide(incumbent, competitor, incumbent="CLOUD_OPEND")
    assert d["proposed_source"] == "CLOUD_OPEND"
    assert d["switch_reason"] == "INCUMBENT_HELD_ANTI_FLAP"


def test_independent_market_and_timeframe_prevent_cross_writer():
    with pytest.raises(ValueError):
        decide(source("TENCENT", market="CN", symbol="159611"))
    with pytest.raises(ValueError):
        decide(source(timeframe="15m"))
    with pytest.raises(ValueError):
        decide(source(), source())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_invalid_latency_does_not_enter_source_race(value):
    with pytest.raises(ValueError):
        source(latency=value)


def test_unknown_source_and_invalid_clock_fail_closed():
    with pytest.raises(ValueError):
        source("UNKNOWN_PRIVATE_API")
    with pytest.raises(ValueError):
        source(observed_at_utc=NOW.replace(tzinfo=None))


def test_crosscheck_unknown_never_claimed_pass():
    a=source(crosscheck_status="UNKNOWN")
    d=decide(a)
    assert d["crosscheck_status"] == "UNKNOWN"
    assert d["canonical_write_authorized"] is False

def test_cn_qualified_tickflow_first_regardless_of_fallback_latency():
    kw={"market":"CN","symbol":"159611","timeframe":"15m"}
    slow_cloud=source("CLOUD_TICKFLOW",latency=60,**kw)
    fast_backup=source("EASTMONEY",latency=1,**kw)
    choice=decide(slow_cloud,fast_backup,incumbent="EASTMONEY",**kw)
    assert choice["decision"]=="SHADOW_PROPOSAL"
    assert choice["proposed_source"]=="CLOUD_TICKFLOW"
    assert choice["switch_reason"]=="PREFERRED_TICKFLOW_QUALIFIED"
    assert choice["canonical_write_authorized"] is False
    assert choice["radar_admission"]=="BLOCKED"


def test_cn_unqualified_tickflow_falls_back_without_admission():
    kw={"market":"CN","symbol":"159611","timeframe":"60m"}
    no_entitlement=source("DESKTOP_TICKFLOW",latency=1,entitlement_qualified="UNKNOWN",**kw)
    backup=source("TENCENT",latency=10,**kw)
    choice=decide(no_entitlement,backup,**kw)
    assert choice["proposed_source"]=="TENCENT"
    assert choice["source_preference_order"][:2]==["CLOUD_TICKFLOW","DESKTOP_TICKFLOW"]
    assert choice["canonical_write_authorized"] is False
    assert choice["live_trade"] is False


def test_cn_two_qualified_tickflow_host_sources_pick_lowest_latency():
    kw={"market":"CN","symbol":"159611","timeframe":"15m"}
    cloud=source("CLOUD_TICKFLOW",latency=7,**kw)
    desktop=source("DESKTOP_TICKFLOW",latency=12,**kw)
    choice=decide(cloud,desktop,**kw)
    assert choice["proposed_source"]=="CLOUD_TICKFLOW"
    assert choice["source_preference_order"][:2]==["CLOUD_TICKFLOW","DESKTOP_TICKFLOW"]


def test_cn_tickflow_stale_never_selected_even_with_preference():
    kw={"market":"CN","symbol":"159611","timeframe":"15m"}
    old=source("CLOUD_TICKFLOW",latency=1,observed_at_utc=NOW-timedelta(hours=1),**kw)
    fallback=source("EASTMONEY",latency=10,**kw)
    choice=decide(old,fallback,**kw)
    assert choice["proposed_source"]=="EASTMONEY"
    assert "STALE_QUALIFICATION_EVIDENCE" in choice["rejected_source_reasons"]["CLOUD_TICKFLOW"]
