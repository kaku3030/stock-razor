from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.execution_engine import AccountSnapshot, OrderIntent, OrderType, ReconciliationSnapshot, RiskContext, RiskGuard, RiskLimits, Side
from src.services.live_shadow import ShadowExecutionCapability
from src.services.execution_engine import ExecutionStore
from src.services.stock_radar_v2.execution_reality import DivergenceStatus, ShadowDivergenceRecord


NOW = datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc)


def make_intent(name="i-1", **kwargs):
    return OrderIntent(name, "AMD", Side.BUY, OrderType.LIMIT, Decimal("10"), limit_price=Decimal("100"),
                       max_slippage=Decimal("0.001"), strategy_id="strategy", evidence_snapshot_id="evidence",
                       account_target="paper", broker_target="paper", **kwargs)


def setup(store=None):
    limits = RiskLimits(frozenset({"AMD"}), Decimal("5000"), Decimal("100"), Decimal("10000"), Decimal("20000"), Decimal("0.01"), 10, 60, 60)
    recon = ReconciliationSnapshot(AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"), as_of=NOW)
    return ShadowExecutionCapability(RiskGuard(limits), store), recon


def test_shadow_public_surface_has_preview_only_and_no_mutation():
    capability, _ = setup()
    public = {name for name in dir(capability) if not name.startswith("_")}
    assert public == {"preview"}


def test_pass_preview_has_zero_broker_mutations_and_is_deterministic():
    capability, recon = setup()
    first = capability.preview(make_intent(), RiskContext(NOW, NOW, "RTH"), recon, "account-gen-1")
    second = capability.preview(make_intent(), RiskContext(NOW, NOW, "RTH"), recon, "account-gen-1")
    assert first == second
    assert first.eligible_for_execution
    assert first.preview.mutation_allowed is False


def test_risk_veto_stale_inputs_is_blocked_and_not_qualified():
    capability, recon = setup()
    result = capability.preview(make_intent(), RiskContext(NOW, NOW - timedelta(seconds=61), "RTH"), recon, "account-gen-1")
    assert not result.eligible_for_execution
    assert result.risk_result == "BLOCKED"


@pytest.mark.parametrize("reconciliation", [
    ReconciliationSnapshot(AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW - timedelta(seconds=61), "paper"), as_of=NOW),
    ReconciliationSnapshot(AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"), as_of=None),
])
def test_stale_or_unknown_account_is_not_qualified(reconciliation):
    capability, _ = setup()
    result = capability.preview(make_intent(), RiskContext(NOW, NOW, "RTH"), reconciliation, "account-gen-1")
    assert result.gate_result == "NOT_QUALIFIED"
    assert not result.eligible_for_execution


def test_expired_intent_and_wrong_session_are_not_qualified():
    capability, recon = setup()
    expired = capability.preview(make_intent(valid_until=NOW - timedelta(seconds=1)), RiskContext(NOW, NOW, "RTH"), recon, "account-gen-expired")
    wrong_session = capability.preview(make_intent(), RiskContext(NOW, NOW, "AH"), recon, "account-gen-ah")
    assert expired.reason == "intent is expired"
    assert wrong_session.reason == "session is not allowed"


def test_preview_is_not_order_or_fill_truth():
    capability, recon = setup()
    result = capability.preview(make_intent(), RiskContext(NOW, NOW, "RTH"), recon, "account-gen-1")
    assert not hasattr(result.preview, "broker_order_id")
    assert not hasattr(result.preview, "fill_ids")
    assert not hasattr(result.preview, "fill_price")


def test_distinct_intents_have_distinct_decisions_and_restart_is_idempotent(tmp_path):
    path = tmp_path / "shadow.sqlite"
    first, recon = setup(ExecutionStore(path))
    context = RiskContext(NOW, NOW, "RTH")
    first_result = first.preview(make_intent(), context, recon, "account-gen-1")
    second_result = first.preview(make_intent("i-2"), context, recon, "account-gen-1")
    reopened, _ = setup(ExecutionStore(path))
    assert reopened.preview(make_intent(), context, recon, "account-gen-1") == first_result
    assert second_result.decision_id != first_result.decision_id
    assert len([event for event in reopened._store.events() if event.kind == "SHADOW_DECISION"]) == 2


def test_intent_risk_fields_survive_restart(tmp_path):
    store = ExecutionStore(tmp_path / "intent.sqlite")
    intent = make_intent(stop_price=Decimal("95"), invalidation=Decimal("90"), risk_budget_r=Decimal("1.5"), valid_until=NOW + timedelta(minutes=5))
    store.save_intent(intent)
    restored = store.intents()[0]
    assert restored.stop_price == intent.stop_price
    assert restored.invalidation == intent.invalidation
    assert restored.risk_budget_r == intent.risk_budget_r
    assert restored.valid_until == intent.valid_until


def test_divergence_unknown_does_not_auto_upgrade():
    record = ShadowDivergenceRecord("decision-1")
    compared = record.compare_observed("manual-observation")
    assert record.decision is DivergenceStatus.UNKNOWN
    assert compared.decision is DivergenceStatus.UNKNOWN
    assert compared.observed_outcome == "manual-observation"
    assert compared.account_truth is DivergenceStatus.UNKNOWN
