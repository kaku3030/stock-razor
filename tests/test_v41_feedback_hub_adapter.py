from data_provider.cn_fast_research_brief import build_cn_main_control_report_v41
from data_provider.radar_report_v41 import build_report, submit_report_feedback
from data_provider.us_fast_research_brief import build_us_main_control_report_v41


class FakeHub:
    def __init__(self):
        self.calls = []

    def submit(self, **kwargs):
        self.calls.append(kwargs)
        return {"accepted": True, "dedupe_key": kwargs["dedupe_key"]}


def _blocked(market, symbol, *, evidence=None):
    return build_report(
        market, symbol, evidence,
        received_at_utc="2026-10-19T02:00:00+00:00",
        report_completed_at_utc="2026-10-19T02:00:00.090+00:00",
    )


def test_blocked_report_submits_only_sanitized_deduplicated_evidence():
    hub = FakeHub()
    report = _blocked("US", "AAPL")
    report["endpoint_evidence"]["AWS"] = {
        "opaque_payload": {"api_key": "MUST_NOT_BE_COPIED"},
    }

    result = submit_report_feedback(report, hub)

    assert result["accepted"] is True
    assert len(hub.calls) == 1
    call = hub.calls[0]
    assert call["source"] == "US_RADAR"
    assert call["priority"] == "P1"
    assert call["dedupe_key"] == report["feedback"]["dedupe_key"]
    assert call["source_ref"].startswith("v41:US:AAPL:")
    assert "opaque_payload" not in repr(call)
    assert "MUST_NOT_BE_COPIED" not in repr(call)
    assert call["evidence"]["status"] == "BLOCKED"
    assert call["evidence"]["reason"] == "V4_1_ACCEPTANCE_DEFECT"


def test_no_defect_report_does_not_write_to_feedback_hub():
    hub = FakeHub()
    report = _blocked("US", "AAPL")
    report["status"] = "PASS_RESEARCH_ONLY"
    report["feedback"]["status"] = "NO_DEFECT"
    assert submit_report_feedback(report, hub) is None
    assert hub.calls == []


def test_malformed_feedback_identity_fails_closed_before_write():
    hub = FakeHub()
    report = _blocked("CN", "600000")
    report["feedback"]["dedupe_key"] = "not-a-digest"
    try:
        submit_report_feedback(report, hub)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed dedupe key must be rejected")
    assert hub.calls == []


def test_cn_and_us_producer_adapters_forward_blockers_when_hub_is_injected():
    for builder, symbol, expected_source in (
        (build_cn_main_control_report_v41, "600000", "CN_RADAR"),
        (build_us_main_control_report_v41, "AAPL", "US_RADAR"),
    ):
        hub = FakeHub()
        report = builder(symbol, feedback_hub=hub)
        assert report["status"] == "BLOCKED"
        assert len(hub.calls) == 1
        assert hub.calls[0]["source"] == expected_source
        assert hub.calls[0]["dedupe_key"] == report["feedback"]["dedupe_key"]


def test_malformed_or_conflicting_report_never_reaches_hub():
    hub = FakeHub()
    report = _blocked("CN", "600000")
    report["status"] = "PASS_RESEARCH_ONLY"
    try:
        submit_report_feedback(report, hub)
    except ValueError:
        pass
    else:
        raise AssertionError("conflicting report must be rejected")
    assert hub.calls == []
