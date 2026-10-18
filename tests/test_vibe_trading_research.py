import pytest

from scripts.vibe_trading_research import parse_request


def test_natural_language_request_maps_to_research_only_profile() -> None:
    result = parse_request("run Strong Pullback in Replay Lab")
    assert result["profile"] == "strong_pullback"
    assert result["execution"] == "NOT_RUN"
    assert result["radar_admission"] == "BLOCKED"
    assert result["trade_execution"] == "NO"


def test_ambiguous_request_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        parse_request("compare B0 and V0.2")
