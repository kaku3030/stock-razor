from decimal import Decimal

from src.services.paper_replay_report import build_paper_replay_report
from src.services.paper_trade_review import PaperReviewStatus, PaperTradeReview
from src.services.trade_lifecycle import LifecycleDecision, LifecycleStage, TradeLifecycleSnapshot
from datetime import datetime, timezone


NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def lifecycle(decision, index):
    return TradeLifecycleSnapshot(
        lifecycle_id=f"lifecycle-{index}",
        as_of=NOW,
        stage=LifecycleStage.PLAN,
        decision=decision,
        plan_id=f"plan-{index}",
        position_id=None,
        reasons=(),
    )


def test_report_aggregates_decisions_reviews_and_keeps_gates_blocked():
    report = build_paper_replay_report(
        "replay-20261010-001",
        (
            lifecycle(LifecycleDecision.WAIT, 1),
            lifecycle(LifecycleDecision.NO_TRADE, 2),
            lifecycle(LifecycleDecision.ENTRY_BLOCKED, 3),
            lifecycle(LifecycleDecision.PLAN_PASS, 4),
        ),
        (
            PaperTradeReview(
                PaperReviewStatus.COMPLETED,
                "plan-4",
                (),
                realized_pnl=Decimal("12.5"),
                realized_r=Decimal("0.5"),
            ),
            PaperTradeReview(
                PaperReviewStatus.BLOCKED,
                "plan-5",
                ("STOP_PRICE_REQUIRED",),
            ),
        ),
    )
    assert report.lifecycle_count == 4
    assert (report.wait_count, report.no_trade_count, report.entry_blocked_count) == (1, 1, 1)
    assert report.plan_pass_count == 1
    assert report.completed_review_count == 1
    assert report.blocked_review_count == 1
    assert report.realized_pnl_total == Decimal("12.5")
    assert report.realized_r_total == Decimal("0.5")
    assert report.blocked_reasons == ("STOP_PRICE_REQUIRED",)
    assert report.paper_auto_ready is False
    assert report.radar_admission == "BLOCKED"
    assert report.live_trade == "NO"


def test_report_requires_an_id():
    try:
        build_paper_replay_report("", (), ())
    except ValueError as exc:
        assert str(exc) == "report_id is required"
    else:
        raise AssertionError("missing report id must fail closed")
