from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from scripts.us_opend_30m_audit import evaluate_schedule, prepare, summarize_probe

NY = ZoneInfo("America/New_York")


def et(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=NY)


def test_dst_keeps_0930_slot_in_new_york_time():
    assert evaluate_schedule(et("2026-03-09 09:30")).eligible
    assert evaluate_schedule(datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc)).eligible


def test_weekend_and_nyse_holiday_are_not_due():
    assert evaluate_schedule(et("2026-03-07 10:00")).status == "NON_TRADING_DAY"
    assert evaluate_schedule(et("2026-07-03 10:00")).status == "NON_TRADING_DAY"


def test_early_close_uses_calendar_close_and_does_not_create_late_slot():
    assert evaluate_schedule(et("2026-11-27 13:00")).eligible
    assert evaluate_schedule(et("2026-11-27 13:30")).status == "OUTSIDE_RTH"


def test_feedback_hub_is_queried_and_slot_is_deduplicated(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    first = prepare(path, et("2026-10-16 10:00"))
    second = prepare(path, et("2026-10-16 10:00"))
    assert first["feedback"]["id"] == second["feedback"]["id"]
    assert first["feedback_preflight"]["status"] == "READY"


def test_missing_quality_layers_stay_not_verified():
    result = summarize_probe({"symbols": ["US.AAPL"], "runtime_exact_sha": "PASS"})
    assert result["quality"]["5m"] == "NOT_VERIFIED"
    assert result["quality"]["D1"] == "NOT_VERIFIED"
    assert result["quality"]["dynamic_subscription"] == "NOT_VERIFIED"
    assert result["signals"]["status"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"


def test_probe_step_has_explicit_github_token():
    """A prior step's GH_TOKEN cannot authenticate this later gh api call."""
    path = Path(__file__).resolve().parents[1] / ".github/workflows/audit-us-opend-30m-readonly.yml"
    workflow = path.read_text(encoding="utf-8")
    probe = workflow.split("      - name: Run bounded existing-export probe over SSM\n", 1)[1]
    probe = probe.split("      - name: Write back sanitized evidence\n", 1)[0]
    assert "GH_TOKEN: ${{ github.token }}" in probe
    assert "gh api" in probe
