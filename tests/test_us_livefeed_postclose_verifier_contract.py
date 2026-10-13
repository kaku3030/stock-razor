"""US LiveFeed acceptance must match guarded OpenD history provenance.

Regression on *verification* contract; no AWS/probe/network/order operations.
The actual SSM deployment acceptance remains the independent cloud gate.
"""
from pathlib import Path

from src.services.live_feed.futu_k1m_history import (
    normalize_futu_k1m_history_rows,
)
from src.services.live_feed.futu_k1m_warm_start import (
    build_futu_k1m_warm_start_selection,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ops/aws/verify_us_opend_livefeed.sh"
HISTORY = ROOT / "src/services/live_feed/futu_k1m_history.py"
WARM = ROOT / "src/services/live_feed/futu_k1m_warm_start.py"


def test_acceptance_allows_both_structurally_guarded_terminal_methods():
    script = SOURCE.read_text(encoding="utf-8")
    assert "QUALIFIED_PRIOR_SESSION_FULL_GRID" in script
    assert "QUALIFIED_POST_SESSION_FULL_GRID" in script
    assert 'assert set(methods) <= {"NEXT_TIME_KEY_PROGRESS"} | terminal_methods' in script
    assert "terminal_count = sum(method in terminal_methods for method in methods)" in script
    assert "assert terminal_count in {0, 1}" in script
    assert "assert methods[-1] in terminal_methods" in script
    assert "assert len(anchors) == 2" in script
    assert 'assert item.get("closure_anchor_time_key") is None' in script
    assert 'assert methods == ["NEXT_TIME_KEY_PROGRESS"] * 3' in script
    assert "assert len(anchors) == 3" in script
    assert 'assert item.get("closure_anchor_time_key")' in script
    # Old gate *forbade* new source's same-day postclose method, so after an
    # actually successful restart the SSM acceptance step returned FAIL.
    assert "terminal_count = methods.count(\"QUALIFIED_PRIOR_SESSION_FULL_GRID\")" not in script

    history = HISTORY.read_text(encoding="utf-8")
    warm = WARM.read_text(encoding="utf-8")
    assert 'else "QUALIFIED_PRIOR_SESSION_FULL_GRID" if terminal_closed' in history
    assert '"QUALIFIED_POST_SESSION_FULL_GRID" if terminal_same_day' in history
    assert '"QUALIFIED_POST_SESSION_FULL_GRID",' in warm

    # Preserve all admission and currentness checks through this source-only
    # verifier change. Terminal historical eligibility is NOT live qualification.
    for guard in (
        'assert heartbeat.get("radar_admission") == "BLOCKED"',
        'assert heartbeat.get("live_trade") is False',
        'assert warm_start.get("realtime_currentness_proven") is False',
        'assert warm_start.get("bar_closure_promotion_authorized") is False',
        'assert item.get("current_session_catchup_closure_method") == "NEXT_TIME_KEY_PROGRESS"',
        'assert snapshot.get("radar_admission") == "BLOCKED"',
        'assert snapshot.get("live_trade") is False',
    ):
        assert guard in script


def test_contract_observed_livefeed_acceptance_not_equal_realtime_evidence():
    source = SOURCE.read_text(encoding="utf-8")
    assert "intraday_closure_15m_60m_summary" in source
    assert 'heartbeat.get("intraday_closure_15m_60m_summary") == "PASS"' in source
    assert 'heartbeat.get("bar_closure") == expected_bar_closure' in source
    assert 'snapshot.get("bar_closure") == expected_bar_closure' in source
    assert 'currentness_summary == "PASS" and closure_summary == "PASS"' in source
    assert "US_OPEND_LIVEFEED_ACCEPTANCE_TIMEOUT" in source

