import pytest

from scripts.vibe_trading_research import parse_request, render_markdown


def test_natural_language_request_maps_to_research_only_profile() -> None:
    result = parse_request("run Strong Pullback in Replay Lab")
    assert result["profile"] == "strong_pullback"
    assert result["execution"] == "NOT_RUN"
    assert result["radar_admission"] == "BLOCKED"
    assert result["trade_execution"] == "NO"


def test_ambiguous_request_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        parse_request("compare B0 and V0.2")


def test_comparison_request_selects_multiple_profiles() -> None:
    from scripts.vibe_trading_research import parse_comparison_request

    result = parse_comparison_request("compare B0, V0.2, and Strong Pullback")
    assert result["profiles"] == ("b0", "v0.2", "strong_pullback")
    assert result["execution"] == "NOT_RUN"


def test_markdown_report_preserves_blocked_data_gate() -> None:
    report = render_markdown({
        "status": "RESEARCH_ONLY",
        "execution": "REPLAY_COMPLETED",
        "radar_admission": "BLOCKED",
        "replay": {
            "data_audit": {"status": "BLOCKED"},
            "inputs": [{"symbol": "QQQ", "rows": 78, "data_audit": {"historical_replay": {"eligibility": "BLOCKED"}}}],
        },
    })
    assert "`BLOCKED`" in report
    assert "QQQ" in report


def test_markdown_report_labels_fixture_smoke() -> None:
    report = render_markdown({
        "status": "RESEARCH_ONLY",
        "execution": "REPLAY_COMPLETED",
        "radar_admission": "BLOCKED",
        "replay": {
            "input_kind": "FIXTURE_SMOKE",
            "data_audit": {"status": "NOT_VERIFIED"},
        },
    })
    assert "`FIXTURE_SMOKE`" in report
    assert "`NOT_VERIFIED`" in report
