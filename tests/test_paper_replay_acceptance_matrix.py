"""Deterministic acceptance matrix for the offline paper replay chain."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.execution_engine import Side
from src.services.paper_replay_report import build_paper_replay_report
from src.services.paper_shadow_readiness import (
    ShadowReadiness,
    assess_read_only_shadow_readiness,
)
from src.services.paper_trade_review import (
    PaperReplayFill,
    PaperReviewStatus,
    review_completed_paper_trade,
)
from src.services.trade_lifecycle import (
    LifecycleDecision,
    LifecycleStage,
    TradeLifecycleSnapshot,
)
from src.services.trade_plan import TradeDirection, TradeHorizon, TradePlan


NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def _plan(direction=TradeDirection.LONG, stop=Decimal("98")):
    return TradePlan(
        "matrix-plan", "v0.2", "AAPL", direction, "replay", TradeHorizon.INTRADAY,
        Decimal("100"), Decimal("101"), NOW + timedelta(minutes=5), "5m",
        "invalidated", stop, Decimal("106"), Decimal("10"), Decimal("1"),
        Decimal("0"), Decimal("0"), "offline", 0, "PASS", "SIMULATED",
    )


def _fill(side, price, minute=0, quantity=Decimal("10")):
    return PaperReplayFill(
        side, quantity, Decimal(price), NOW + timedelta(minutes=minute)
    )


def _lifecycle(decision, index):
    reasons = {
        LifecycleDecision.WAIT: ("WAIT_NO_ENTRY",),
        LifecycleDecision.NO_TRADE: ("NO_TRADE_DECLARED",),
        LifecycleDecision.ENTRY_BLOCKED: ("EXECUTION_EVIDENCE_NOT_READY",),
    }.get(decision, ())
    return TradeLifecycleSnapshot(
        f"lifecycle-{index}", NOW, LifecycleStage.PLAN, decision,
        f"plan-{index}", None, reasons,
    )


def test_offline_replay_acceptance_matrix_covers_long_short_and_failures():
    long_review = review_completed_paper_trade(
        _plan(), _fill(Side.BUY, "100"), _fill(Side.SELL, "104", 20),
        observed_prices=(Decimal("99"), Decimal("106")),
    )
    short_review = review_completed_paper_trade(
        _plan(TradeDirection.SHORT, Decimal("102")),
        _fill(Side.SELL, "100"), _fill(Side.BUY, "96", 20),
        observed_prices=(Decimal("103"), Decimal("94")),
    )
    quantity_block = review_completed_paper_trade(
        _plan(), _fill(Side.BUY, "100"),
        _fill(Side.SELL, "104", 20, Decimal("9")),
    )
    stop_block = review_completed_paper_trade(
        _plan(stop=None), _fill(Side.BUY, "100"), _fill(Side.SELL, "104", 20),
    )
    assert long_review.status is PaperReviewStatus.COMPLETED
    assert short_review.status is PaperReviewStatus.COMPLETED
    assert long_review.realized_r == Decimal("2")
    assert short_review.realized_r == Decimal("2")
    assert quantity_block.reasons == ("ENTRY_EXIT_QUANTITY_MISMATCH",)
    assert stop_block.reasons == ("STOP_PRICE_REQUIRED",)

    report = build_paper_replay_report(
        "matrix-1",
        (
            _lifecycle(LifecycleDecision.WAIT, 1),
            _lifecycle(LifecycleDecision.NO_TRADE, 2),
            _lifecycle(LifecycleDecision.ENTRY_BLOCKED, 3),
            _lifecycle(LifecycleDecision.PLAN_PASS, 4),
        ),
        (long_review, short_review, quantity_block, stop_block),
    )
    assert (report.wait_count, report.no_trade_count) == (1, 1)
    assert (report.entry_blocked_count, report.plan_pass_count) == (1, 1)
    assert report.non_trade_reasons == (
        "WAIT_NO_ENTRY",
        "NO_TRADE_DECLARED",
        "EXECUTION_EVIDENCE_NOT_READY",
    )
    assert report.non_trade_reason_coverage_passed is True
    assert report.completed_review_count == 2
    assert report.blocked_review_count == 2
    assert report.realized_r_total == Decimal("4")

    not_ready = assess_read_only_shadow_readiness(
        report,
        replay_passed=True,
        restart_reconciliation_passed=False,
        failure_injection_passed=False,
        non_trade_reason_coverage_passed=True,
        audit_integrity_passed=True,
    )
    assert not_ready.status is ShadowReadiness.NOT_READY

    all_evidence = assess_read_only_shadow_readiness(
        report,
        replay_passed=True,
        restart_reconciliation_passed=True,
        failure_injection_passed=True,
        non_trade_reason_coverage_passed=True,
        audit_integrity_passed=True,
    )
    assert all_evidence.status is ShadowReadiness.READY_READ_ONLY_SHADOW
    assert all_evidence.radar_admission == "BLOCKED"
    assert all_evidence.paper_auto_ready is False
    assert all_evidence.live_trade == "NO"
