"""Research Data Capture must not silently pass when a provider blocks data."""

from pathlib import Path

import yaml


WORKFLOW = yaml.safe_load(
    Path(".github/workflows/research-data-capture.yml").read_text(encoding="utf-8")
)
STEPS = WORKFLOW["jobs"]["capture"]["steps"]


def _step(name: str) -> dict:
    return next(step for step in STEPS if step.get("name") == name)


def test_optional_network_capture_is_followed_by_mandatory_complete_validation():
    # Capture is best-effort so blocked manifests can be uploaded as evidence,
    # but downstream validation MUST fail the overall job on any missing data.
    assert _step("Capture frozen research universe")["continue-on-error"] is True
    assert _step("Capture A-share EOD")["continue-on-error"] is True
    assert _step("Capture US EOD")["continue-on-error"] is True
    validation = _step("Validate recorded captures")
    assert not validation.get("continue-on-error", False)
    run = validation["run"]
    assert "scripts/validate_research_universe_capture.py" in run
    assert "--config config/research_universe_v0_1.json" in run
    assert "--evidence-report artifacts/universe/capture_evidence.json" in run
    assert "|| capture_status=2" in run
    assert "for market in cn_600000 us_SPY" in run
    assert 'if [ ! -f "$csv" ] || [ ! -f "$manifest" ]' in run
    assert "scripts/validate_recorded_capture.py" in run
    assert 'exit "$capture_status"' in run
    assert "SKIPPED:" not in run


def test_capture_failure_still_uploads_diagnostic_evidence():
    upload = _step("Upload recorded captures and manifests")
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "artifacts/"
