from api.v1.endpoints.research_validation import ResearchValidationConfig

def test_research_config_requires_research_only():
    config = ResearchValidationConfig(
        rule_id="demo",
        symbol="sh.600000",
        development_end="2024-12-31",
        validation_end="2025-12-31",
        holdout_id="holdout-v1",
    )
    assert config.research_only is True
    assert "with_rule" in config.counterfactuals

def test_research_config_rejects_unknown_counterfactual():
    try:
        ResearchValidationConfig(
            rule_id="demo",
            symbol="SPY",
            development_end="2024-12-31",
            validation_end="2025-12-31",
            holdout_id="holdout-v1",
            counterfactuals=["future_rule"],
        )
    except ValueError as exc:
        assert "unsupported counterfactuals" in str(exc)
    else:
        raise AssertionError("unknown counterfactual was accepted")


def test_research_config_rejects_inverted_dates():
    try:
        ResearchValidationConfig(
            rule_id="demo", symbol="SPY", development_end="2026-01-01",
            validation_end="2025-01-01", holdout_id="holdout-v1",
        )
    except ValueError as exc:
        assert "development_end must be before validation_end" in str(exc)
    else:
        raise AssertionError("inverted dates were accepted")


import asyncio
from api.v1.endpoints.research_validation import get_research_status


def test_research_status_does_not_expose_token(monkeypatch):
    monkeypatch.setenv("RADAR_GITHUB_TOKEN", "secret-value")
    payload = asyncio.run(get_research_status())
    assert payload["artifact_proxy_configured"] is True
    assert payload["research_only"] is True
    assert payload["production_promotion"] == "locked"
    assert "secret-value" not in str(payload)
