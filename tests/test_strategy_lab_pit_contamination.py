"""Permanent negative fixtures for PIT / LLM contamination (S2, Sandbox).

Each frozen contamination mode A..N has exactly one negative fixture proving
that the leak is detected (``passed=False`` = VALIDATION HARD FAIL), plus a
positive control proving a clean input is accepted. These are adversarial
regressions: if any future change makes a leak pass, that is a hard failure of
the contract -- do not merge.

No production runtime, provider, replay engine, or external OSS runtime is
imported or exercised here. Only the pure ``pit_contamination`` predicates and
native ``temporal_contract``/``validation_models`` contracts are used.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.strategy_lab.pit_contamination import (
    assess_benchmark_window_memorization,
    assess_entity_recognition_leakage,
    assess_future_bar_leakage,
    assess_future_publication_leakage,
    assess_historical_date_recognition_leakage,
    assess_latest_financials_for_replay,
    assess_nearest_abs_future_selection,
    assess_prompt_metadata_window_leakage,
    assess_replay_tamper,
    assess_report_period_as_publication,
    assess_symmetric_window_future_leakage,
    assess_timezone_naive_epoch,
    assess_tool_output_unmasked_leakage,
    assess_unseeded_random,
)

UTC = timezone.utc


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


D = _dt(2026, 3, 10)          # decision instant (UTC)
PREV = _dt(2026, 3, 9, 16)
AFTER = _dt(2026, 3, 10, 16)


# ---------------------------------------------------------------------------
# A. Future bar leakage.
# ---------------------------------------------------------------------------


def test_A_future_bar_is_flagged() -> None:
    result = assess_future_bar_leakage(bar_time=AFTER, decision_time=D)
    assert result.gate == "pit_future_bar"
    assert result.passed is False
    assert result.reason == "future_bar_used"


def test_A_bar_at_or_before_decision_is_clean() -> None:
    assert assess_future_bar_leakage(bar_time=PREV, decision_time=D).passed is True
    assert assess_future_bar_leakage(bar_time=D, decision_time=D).passed is True


# ---------------------------------------------------------------------------
# B. Future announcement / publication leakage.
# ---------------------------------------------------------------------------


def test_B_future_publication_is_flagged() -> None:
    result = assess_future_publication_leakage(publication_time=AFTER, decision_time=D)
    assert result.passed is False
    assert result.reason == "future_publication_used"


def test_B_publication_at_or_before_decision_is_clean() -> None:
    assert assess_future_publication_leakage(publication_time=PREV, decision_time=D).passed is True


# ---------------------------------------------------------------------------
# C. Historical date recognition leakage.
# ---------------------------------------------------------------------------


def test_C_absolute_date_in_prompt_is_flagged() -> None:
    result = assess_historical_date_recognition_leakage(
        prompt_text="Today the market review is for 2026-03-10.",
        sensitive_dates=["2026-03-10", "2026-03-11"],
    )
    assert result.passed is False
    assert result.evidence["matched_dates"] == ["2026-03-10"]


def test_C_prompt_without_sensitive_date_is_clean() -> None:
    result = assess_historical_date_recognition_leakage(
        prompt_text="Review recent momentum, no dates mentioned.",
        sensitive_dates=["2026-03-10"],
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# D. Company / entity recognition leakage.
# ---------------------------------------------------------------------------


def test_D_unmasked_entity_is_flagged() -> None:
    result = assess_entity_recognition_leakage(
        prompt_text="Buy 贵州茅台 on strength.",
        masked_entities=["贵州茅台", "600519"],
    )
    assert result.passed is False
    assert result.evidence["matched_entities"] == ["贵州茅台"]


def test_D_masked_prompt_is_clean() -> None:
    result = assess_entity_recognition_leakage(
        prompt_text="Buy {{C000001}} on strength.",
        masked_entities=["贵州茅台", "600519"],
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# E. report_period treated as publication_time.
# ---------------------------------------------------------------------------


def test_E_future_publication_visible_is_flagged() -> None:
    # publication_time after decision_time, presented as visible => HARD FAIL,
    # regardless of report_period.
    result = assess_report_period_as_publication(
        report_period=_dt(2026, 3, 31),
        publication_time=_dt(2026, 4, 15),
        decision_time=_dt(2026, 4, 10),
        evidence_visible=True,
    )
    assert result.passed is False
    assert result.reason == "future_publication_visible"


def test_E_report_period_not_equal_publication_is_not_required() -> None:
    # report_period != publication_time is NORMAL, not a leak: the forbidden
    # thing is using report_period AS publication. publication <= decision =>
    # allowed independent of report_period (even if report_period post-dates
    # publication, or differs).
    result = assess_report_period_as_publication(
        report_period=_dt(2026, 3, 31),      # quarter end
        publication_time=_dt(2026, 4, 15),   # published later
        decision_time=_dt(2026, 4, 20),      # decision after publication
        evidence_visible=True,
    )
    assert result.passed is True


def test_E_future_publication_but_not_visible_is_not_leaked() -> None:
    # publication > decision but evidence_visible=False => the caller does NOT
    # claim it was available, so no leak is asserted.
    result = assess_report_period_as_publication(
        report_period=_dt(2026, 3, 31),
        publication_time=_dt(2026, 4, 15),
        decision_time=_dt(2026, 4, 10),
        evidence_visible=False,
    )
    assert result.passed is True


def test_E_unknown_visibility_fails_closed() -> None:
    result = assess_report_period_as_publication(
        report_period=_dt(2026, 3, 31),
        publication_time=_dt(2026, 4, 15),
        decision_time=_dt(2026, 4, 20),
        evidence_visible=None,  # unknown availability claim
    )
    assert result.passed is False
    assert result.reason == "evidence_visibility_unknown"


# ---------------------------------------------------------------------------
# F. nearest(abs(target-date)) selecting future data.
# ---------------------------------------------------------------------------


def test_F_nearest_abs_selects_future_is_flagged() -> None:
    # 03-11 is 1 day after target; 03-08 is 2 days before. nearest-by-abs is
    # the future candidate, which must be rejected.
    result = assess_nearest_abs_future_selection(
        target_date=D,
        candidate_dates=[_dt(2026, 3, 8), _dt(2026, 3, 11)],
    )
    assert result.passed is False
    assert result.reason == "future_candidate_selected"


def test_F_nearest_abs_within_past_is_clean() -> None:
    result = assess_nearest_abs_future_selection(
        target_date=D,
        candidate_dates=[_dt(2026, 3, 8), _dt(2026, 3, 9)],
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# G. Symmetric +/-N-day window leaking future data.
# ---------------------------------------------------------------------------


def test_G_symmetric_window_crossing_decision_is_flagged() -> None:
    result = assess_symmetric_window_future_leakage(
        center=D,
        radius=timedelta(days=3),
        decision_time=D,
    )
    assert result.passed is False
    assert result.reason == "window_crosses_decision"


def test_G_symmetric_window_within_decision_is_clean() -> None:
    result = assess_symmetric_window_future_leakage(
        center=_dt(2026, 3, 7),
        radius=timedelta(days=2),  # right edge 03-09 < 03-10
        decision_time=D,
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# H. latest financials used for historical replay.
# ---------------------------------------------------------------------------


def test_H_future_financials_for_replay_is_flagged() -> None:
    result = assess_latest_financials_for_replay(
        financials_as_of=_dt(2026, 6, 30),
        replay_decision_time=D,
    )
    assert result.passed is False
    assert result.reason == "future_financials_used"


def test_H_financials_as_of_before_replay_is_clean() -> None:
    result = assess_latest_financials_for_replay(
        financials_as_of=_dt(2025, 12, 31),
        replay_decision_time=D,
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# I. timezone-naive epoch conversion.
# ---------------------------------------------------------------------------


def test_I_naive_datetime_is_flagged() -> None:
    result = assess_timezone_naive_epoch(value=datetime(2026, 3, 10))
    assert result.passed is False
    assert result.reason == "naive_or_epoch_value"


def test_I_epoch_int_is_flagged() -> None:
    result = assess_timezone_naive_epoch(value=1741564800)
    assert result.passed is False


def test_I_aware_datetime_is_clean() -> None:
    result = assess_timezone_naive_epoch(value=D)
    assert result.passed is True


# ---------------------------------------------------------------------------
# J. unseeded random sampling.
# ---------------------------------------------------------------------------


def test_J_unseeded_is_flagged() -> None:
    result = assess_unseeded_random(seed=None)
    assert result.passed is False
    assert result.reason == "seed_missing"


def test_J_seeded_is_clean() -> None:
    assert assess_unseeded_random(seed=42).passed is True


# ---------------------------------------------------------------------------
# K. prompt metadata revealing evaluation window.
# ---------------------------------------------------------------------------


def test_K_window_metadata_in_prompt_is_flagged() -> None:
    result = assess_prompt_metadata_window_leakage(
        prompt_text='{"eval_window": ["2026-03-01", "2026-03-10"]}',
        sensitive_dates=["2026-03-01", "2026-03-10"],
    )
    assert result.passed is False
    assert result.reason == "window_metadata_present"


def test_K_prompt_without_window_metadata_is_clean() -> None:
    result = assess_prompt_metadata_window_leakage(
        prompt_text="Analyze recent tape.",
        sensitive_dates=["2026-03-01"],
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# L. tool output leaking unmasked ticker/date.
# ---------------------------------------------------------------------------


def test_L_tool_output_with_unmasked_entity_is_flagged() -> None:
    result = assess_tool_output_unmasked_leakage(
        tool_output="close of 600519 is 1500.00",
        masked_entities=["600519", "贵州茅台"],
        sensitive_dates=["2026-03-10"],
    )
    assert result.passed is False
    assert result.reason == "unmasked_entity_or_date"


def test_L_tool_output_clean_is_accepted() -> None:
    result = assess_tool_output_unmasked_leakage(
        tool_output="close of {{C000001}} is 1500.00",
        masked_entities=["600519", "贵州茅台"],
        sensitive_dates=["2026-03-10"],
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# M. benchmark-window memorization clue.
# ---------------------------------------------------------------------------


def test_M_benchmark_constituent_in_prompt_is_flagged() -> None:
    result = assess_benchmark_window_memorization(
        prompt_text="Compare to 贵州茅台 within the window.",
        benchmark_constituents=["贵州茅台", "中国平安"],
    )
    assert result.passed is False
    assert result.reason == "benchmark_constituent_present"


def test_M_no_benchmark_clue_is_clean() -> None:
    result = assess_benchmark_window_memorization(
        prompt_text="Compare to the broad market.",
        benchmark_constituents=["贵州茅台"],
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# N. replay / cassette tamper or contract-version mismatch.
# ---------------------------------------------------------------------------


def test_N_hash_mismatch_is_flagged() -> None:
    result = assess_replay_tamper(
        cassette_sha256="aaa",
        expected_sha256="bbb",
        contract_version="v1",
        expected_contract_version="v1",
    )
    assert result.passed is False
    assert result.reason == "cassette_hash_mismatch"


def test_N_version_mismatch_is_flagged() -> None:
    result = assess_replay_tamper(
        cassette_sha256="same",
        expected_sha256="same",
        contract_version="v1",
        expected_contract_version="v2",
    )
    assert result.passed is False
    assert result.reason == "contract_version_mismatch"


def test_N_intact_replay_is_clean() -> None:
    result = assess_replay_tamper(
        cassette_sha256="same",
        expected_sha256="same",
        contract_version="v1",
        expected_contract_version="v1",
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# Contract integrity: every predicate returns a GateResult with a non-empty
# reason, and a leak always fails (HARD FAIL semantics).
# ---------------------------------------------------------------------------


def test_every_predicate_emits_gate_result_shape() -> None:
    from src.services.strategy_lab.validation_models import GateResult

    results = [
        assess_future_bar_leakage(bar_time=AFTER, decision_time=D),
        assess_future_publication_leakage(publication_time=AFTER, decision_time=D),
        assess_historical_date_recognition_leakage(prompt_text="2026-03-10", sensitive_dates=["2026-03-10"]),
        assess_entity_recognition_leakage(prompt_text="600519", masked_entities=["600519"]),
        assess_report_period_as_publication(
            report_period=_dt(2026, 3, 31),
            publication_time=_dt(2026, 4, 15),
            decision_time=_dt(2026, 4, 10),
            evidence_visible=True,
        ),
        assess_nearest_abs_future_selection(target_date=D, candidate_dates=[AFTER]),
        assess_symmetric_window_future_leakage(center=D, radius=timedelta(days=1), decision_time=D),
        assess_latest_financials_for_replay(financials_as_of=AFTER, replay_decision_time=D),
        assess_timezone_naive_epoch(value=1),
        assess_unseeded_random(seed=None),
        assess_prompt_metadata_window_leakage(prompt_text="2026-03-10", sensitive_dates=["2026-03-10"]),
        assess_tool_output_unmasked_leakage(
            tool_output="600519", masked_entities=["600519"], sensitive_dates=["2026-03-10"]
        ),
        assess_benchmark_window_memorization(prompt_text="贵州茅台", benchmark_constituents=["贵州茅台"]),
        assess_replay_tamper(
            cassette_sha256="a", expected_sha256="b", contract_version="v1", expected_contract_version="v1"
        ),
    ]
    assert len(results) == 14
    for result in results:
        assert isinstance(result, GateResult)
        assert result.passed is False          # every negative fixture is a leak
        assert result.reason.strip()           # and a reason is always stated
