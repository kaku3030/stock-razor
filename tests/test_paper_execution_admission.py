from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.execution_engine import (
    AccountSnapshot,
    ExecutionBlocked,
    ExecutionEngine,
    ExecutionStore,
    OrderState,
    ReconciliationSnapshot,
    RiskContext,
    RiskGuard,
    RiskLimits,
    Side,
    create_paper_adapter,
)
from src.services.live_shadow import ShadowExecutionCapability
from src.services.paper_execution_admission import (
    PaperOrderSpec,
    build_paper_order_intent,
)
from src.services.stock_radar_v2.observation_ledger import Observation


NOW = datetime(2026, 9, 26, 14, 30, tzinfo=timezone.utc)


def permission(**changes) -> Observation:
    values = {
        "observation_id": "obs-amd-001",
        "detector_status": "CONFIRMED",
        "evidence_ids": ("snapshot-amd-001", "entry-gate-amd-001"),
        "strategy_gate_results": {"entry_gate": "PASS"},
        "strategy_eligible": True,
        "portfolio_admissible": True,
        "portfolio_block_reasons": (),
        "execution_feasible": True,
        "decision_available_at": NOW.timestamp() - 2,
        "confirmed_at": NOW.timestamp() - 1,
        "earliest_executable_at": NOW.timestamp() - 1,
        "canonical_permission": "PASS",
    }
    values.update(changes)
    return Observation(**values)


def order_spec(**changes) -> PaperOrderSpec:
    values = {
        "action_id": "action-amd-001",
        "symbol": "AMD",
        "side": Side.BUY,
        "qty": Decimal("10"),
        "limit_price": Decimal("100"),
        "stop_price": Decimal("97"),
        "max_slippage": Decimal("0.001"),
        "invalidation": Decimal("96"),
        "risk_budget_r": Decimal("1"),
        "strategy_id": "paper-entry-v0-1",
        "evidence_snapshot_id": "snapshot-amd-001",
        "valid_until": NOW + timedelta(minutes=5),
        "allowed_session": "RTH",
    }
    values.update(changes)
    return PaperOrderSpec(**values)


def guard() -> RiskGuard:
    return RiskGuard(
        RiskLimits(
            frozenset({"AMD"}),
            Decimal("5000"),
            Decimal("100"),
            Decimal("10000"),
            Decimal("20000"),
            Decimal("0.01"),
            10,
            60,
            60,
        )
    )


def reconciliation() -> ReconciliationSnapshot:
    return ReconciliationSnapshot(
        AccountSnapshot(
            "paper", Decimal("100000"), Decimal("100000"), NOW, "paper"
        ),
        as_of=NOW,
    )


def test_pass_permission_builds_paper_only_limit_intent():
    result = build_paper_order_intent(permission(), order_spec(), now=NOW)

    assert result.intent_id.startswith("paper-")
    assert result.symbol == "AMD"
    assert result.side is Side.BUY
    assert result.order_type.value == "LIMIT"
    assert result.account_target == "paper"
    assert result.broker_target == "paper"
    assert result.evidence_snapshot_id == "snapshot-amd-001"
    assert result.allowed_session == "RTH"


def test_same_action_and_observation_keep_same_idempotency_key_even_if_payload_changes():
    first = build_paper_order_intent(permission(), order_spec(), now=NOW)
    changed = build_paper_order_intent(
        permission(), order_spec(qty=Decimal("5"), limit_price=Decimal("99")), now=NOW
    )

    assert changed.intent_id == first.intent_id
    assert changed.qty != first.qty
    assert changed.limit_price != first.limit_price


@pytest.mark.parametrize(
    "change, message",
    [
        ({"canonical_permission": "UNKNOWN"}, "permission"),
        ({"canonical_permission": "FAIL"}, "permission"),
        ({"strategy_eligible": None}, "strategy"),
        ({"strategy_eligible": False}, "strategy"),
        ({"portfolio_admissible": None}, "portfolio"),
        ({"portfolio_admissible": False}, "portfolio"),
        ({"execution_feasible": None}, "execution feasibility"),
        ({"execution_feasible": False}, "execution feasibility"),
        ({"portfolio_block_reasons": ("RISK_BUDGET",)}, "block reasons"),
    ],
)
def test_unknown_or_blocked_upstream_state_fails_closed(change, message):
    with pytest.raises(ExecutionBlocked, match=message):
        build_paper_order_intent(permission(**change), order_spec(), now=NOW)


def test_evidence_lineage_must_bind_order_to_permission():
    with pytest.raises(ExecutionBlocked, match="evidence"):
        build_paper_order_intent(
            permission(),
            order_spec(evidence_snapshot_id="different-snapshot"),
            now=NOW,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"decision_available_at": None},
        {"confirmed_at": None},
        {"earliest_executable_at": None},
    ],
)
def test_causal_timestamps_are_mandatory(change):
    with pytest.raises(ExecutionBlocked, match="timestamps"):
        build_paper_order_intent(permission(**change), order_spec(), now=NOW)


def test_future_execution_availability_is_blocked():
    future = NOW.timestamp() + 10
    with pytest.raises(ExecutionBlocked, match="not yet"):
        build_paper_order_intent(
            permission(
                decision_available_at=NOW.timestamp(),
                confirmed_at=NOW.timestamp(),
                earliest_executable_at=future,
            ),
            order_spec(),
            now=NOW,
        )


def test_expired_or_naive_valid_until_is_blocked():
    with pytest.raises(ExecutionBlocked, match="expired"):
        build_paper_order_intent(
            permission(), order_spec(valid_until=NOW), now=NOW
        )
    with pytest.raises(ExecutionBlocked, match="timezone-aware"):
        build_paper_order_intent(
            permission(),
            order_spec(valid_until=datetime(2026, 9, 26, 15, 0)),
            now=NOW,
        )


def test_v0_1_rejects_non_rth_session():
    with pytest.raises(ExecutionBlocked, match="RTH"):
        build_paper_order_intent(
            permission(), order_spec(allowed_session="AH"), now=NOW
        )


def test_admitted_intent_flows_through_shadow_then_paper_execution(tmp_path):
    candidate = build_paper_order_intent(permission(), order_spec(), now=NOW)
    risk_guard = guard()
    recon = reconciliation()
    context = RiskContext(NOW, NOW, "RTH")

    shadow = ShadowExecutionCapability(risk_guard)
    preview = shadow.preview(candidate, context, recon, "paper-account-gen-1")
    assert preview.eligible_for_execution
    assert preview.preview is not None
    assert preview.preview.mutation_allowed is False

    fills = {
        candidate.intent_id: (
            ("fill-1", Decimal("4"), Decimal("100")),
            ("fill-2", Decimal("6"), Decimal("100.1")),
        )
    }
    path = tmp_path / "execution.sqlite"
    paper = create_paper_adapter(fills=fills)
    engine = ExecutionEngine(paper, risk_guard, ExecutionStore(path))
    engine.reconciliation = recon

    record = engine.submit(candidate, context)

    assert record.state is OrderState.FILLED
    assert record.filled_qty == Decimal("10")
    assert len(record.fill_ids) == 2
    assert paper.adapter.calls == [("place", candidate.intent_id)]

    reopened_paper = create_paper_adapter()
    reopened = ExecutionEngine(
        reopened_paper, risk_guard, ExecutionStore(path)
    )
    reopened.reconciliation = recon
    with pytest.raises(ExecutionBlocked, match="duplicate"):
        reopened.submit(candidate, context)
    assert reopened_paper.adapter.calls == []


def test_changed_retry_payload_still_collides_at_execution_engine(tmp_path):
    first = build_paper_order_intent(permission(), order_spec(), now=NOW)
    changed = build_paper_order_intent(
        permission(), order_spec(qty=Decimal("5"), limit_price=Decimal("99")), now=NOW
    )
    assert first.intent_id == changed.intent_id

    paper = create_paper_adapter()
    engine = ExecutionEngine(paper, guard(), ExecutionStore(tmp_path / "same-action.sqlite"))
    engine.reconciliation = reconciliation()
    engine.submit(first, RiskContext(NOW, NOW, "RTH"))

    with pytest.raises(ExecutionBlocked, match="duplicate"):
        engine.submit(changed, RiskContext(NOW, NOW, "RTH"))
    assert paper.adapter.calls == [("place", first.intent_id)]


def test_admission_module_does_not_expose_broker_or_network_capability():
    import src.services.paper_execution_admission as module

    public = {name for name in dir(module) if not name.startswith("_")}
    assert "build_paper_order_intent" in public
    assert "create_paper_adapter" not in public
    assert "ExecutionEngine" not in public
    assert not any(name in public for name in ("socket", "requests", "httpx", "futu", "alpaca"))
