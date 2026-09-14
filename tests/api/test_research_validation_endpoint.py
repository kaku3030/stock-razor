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
