from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.external_simulator_readonly_preflight import (
    PaperEvidenceAssessment,
    PaperEvidenceStatus,
    PaperPositionBaseline,
    PaperRealizedFillEvidence,
    PaperReadOnlyScopeStatus,
    assess_independent_realized_fill,
    assess_position_baseline,
)
from src.services.paper_execution_admission import (
    ExternalPaperAdmissionStatus,
    assess_external_paper_admission,
)
from src.services.simulated_account_discovery import (
    AccountMode,
    SimulatedAccountDiscovery,
)


NOW = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)
ACCOUNT = SimulatedAccountDiscovery(
    account_id="123456789",
    mode=AccountMode.SIMULATE,
    market="US",
    authenticated=True,
    observed_at=NOW,
)


def baseline(*, quantity: str, at: datetime, evidence: str) -> PaperPositionBaseline:
    return PaperPositionBaseline(
        account_id=ACCOUNT.account_id,
        account_generation="generation-1",
        observed_at_utc=at,
        source="MOOMOO_OPEND_READONLY",
        readonly_evidence_id=evidence,
        position_quantity=Decimal(quantity),
    )


def fill(**changes) -> PaperRealizedFillEvidence:
    values = dict(
        fill_id="provider-fill-1",
        account_id=ACCOUNT.account_id,
        account_generation="generation-1",
        observed_at_utc=NOW - timedelta(seconds=1),
        source="MOOMOO_OPEND_READONLY",
        readonly_evidence_id="fill-read-1",
        side="BUY",
        filled_quantity=Decimal("2"),
        average_fill_price=Decimal("100"),
        cash_before=Decimal("1000"),
        cash_after=Decimal("799"),
        total_fees=Decimal("1"),
    )
    values.update(changes)
    return PaperRealizedFillEvidence(**values)


def test_position_baseline_passes_only_with_complete_bound_readonly_identity():
    result = assess_position_baseline(
        baseline(quantity="4", at=NOW - timedelta(seconds=2), evidence="pos-before"),
        ACCOUNT,
        expected_account_generation="generation-1",
        expected_source="MOOMOO_OPEND_READONLY",
        expected_readonly_evidence_id="pos-before",
        now_utc=NOW,
    )
    assert result.status is PaperEvidenceStatus.PASS
    assert result.reasons == ()


def test_missing_baseline_provenance_is_unknown_and_never_admitted():
    incomplete = PaperPositionBaseline(
        account_id="",
        account_generation="",
        observed_at_utc=NOW,
        source="",
        readonly_evidence_id="",
        position_quantity=Decimal("0"),
    )
    result = assess_position_baseline(
        incomplete,
        ACCOUNT,
        expected_account_generation="generation-1",
        expected_source="MOOMOO_OPEND_READONLY",
        expected_readonly_evidence_id="pos-before",
        now_utc=NOW,
    )
    assert result.status is PaperEvidenceStatus.UNKNOWN
    assert "POSITION_BASELINE_SOURCE_UNKNOWN" in result.reasons


def test_baseline_identity_generation_source_and_evidence_mismatch_is_blocked():
    result = assess_position_baseline(
        replace(baseline(quantity="4", at=NOW, evidence="pos-before"), account_id="other"),
        ACCOUNT,
        expected_account_generation="generation-1",
        expected_source="MOOMOO_OPEND_READONLY",
        expected_readonly_evidence_id="pos-before",
        now_utc=NOW,
    )
    assert result.status is PaperEvidenceStatus.BLOCKED
    assert "POSITION_BASELINE_ACCOUNT_MISMATCH" in result.reasons


def test_realized_fill_requires_two_independent_baselines_and_separate_fill_readback():
    result = assess_independent_realized_fill(
        baseline(quantity="4", at=NOW - timedelta(seconds=2), evidence="pos-before"),
        baseline(quantity="6", at=NOW, evidence="pos-after"),
        fill(),
        now_utc=NOW,
    )
    assert result.status is PaperEvidenceStatus.PASS
    assert result.reasons == ()

    missing_after = assess_independent_realized_fill(
        baseline(quantity="4", at=NOW - timedelta(seconds=2), evidence="pos-before"),
        None,
        fill(),
        now_utc=NOW,
    )
    assert missing_after.status is PaperEvidenceStatus.UNKNOWN


def test_fixture_ack_dispatch_or_reused_readback_cannot_prove_realized_fill():
    before = baseline(quantity="4", at=NOW - timedelta(seconds=2), evidence="pos-before")
    after = baseline(quantity="6", at=NOW, evidence="pos-after")
    for kind in ("FIXTURE", "ACK", "DISPATCH", "INTENT"):
        result = assess_independent_realized_fill(
            before, after, fill(evidence_kind=kind), now_utc=NOW
        )
        assert result.status is PaperEvidenceStatus.BLOCKED
        assert "REALIZED_FILL_NOT_READONLY_PROVIDER" in result.reasons

    reused = assess_independent_realized_fill(
        before, after, fill(readonly_evidence_id="pos-after"), now_utc=NOW
    )
    assert reused.status is PaperEvidenceStatus.BLOCKED
    assert "REALIZED_FILL_READONLY_EVIDENCE_NOT_INDEPENDENT" in reused.reasons


def test_realized_fill_requires_same_generation_and_exact_position_cash_reconciliation():
    before = baseline(quantity="4", at=NOW - timedelta(seconds=2), evidence="pos-before")
    after = baseline(quantity="6", at=NOW, evidence="pos-after")
    mismatch = assess_independent_realized_fill(
        before, after, fill(account_generation="generation-2"), now_utc=NOW
    )
    assert mismatch.status is PaperEvidenceStatus.BLOCKED
    assert "REALIZED_FILL_GENERATION_MISMATCH" in mismatch.reasons

    bad_cash = assess_independent_realized_fill(
        before, after, fill(cash_after=Decimal("800")), now_utc=NOW
    )
    assert bad_cash.status is PaperEvidenceStatus.BLOCKED
    assert "FILL_CASH_FLOW_MISMATCH" in bad_cash.reasons


def test_fill_model_has_no_intent_ack_or_dispatch_authority_and_module_is_transport_free():
    names = {field.name for field in fields(PaperRealizedFillEvidence)}
    assert not names.intersection({"intent_id", "ack_id", "dispatch_id"})
    import src.services.external_simulator_readonly_preflight as module

    public = {name for name in dir(module) if not name.startswith("_")}
    assert not public.intersection({"requests", "httpx", "socket", "futu", "alpaca"})


def test_external_paper_admission_is_evidence_only_and_never_mutation_ready():
    baseline_result = assess_position_baseline(
        baseline(quantity="4", at=NOW, evidence="pos-before"),
        ACCOUNT,
        expected_account_generation="generation-1",
        expected_source="MOOMOO_OPEND_READONLY",
        expected_readonly_evidence_id="pos-before",
        now_utc=NOW,
    )
    result = assess_external_paper_admission(
        position_baseline=baseline_result,
        readback_scope=PaperReadOnlyScopeStatus.SCOPED_INPUTS_CONSISTENT,
        balance_readback_passed=True,
        open_orders_empty=True,
        independent_fill_source_available=True,
    )
    assert result.status is ExternalPaperAdmissionStatus.READY_FOR_SUPERVISED_REVIEW
    assert result.paper_auto_ready is False
    assert result.broker_mutation_allowed is False
    assert result.live_trade is False


def test_external_paper_admission_keeps_missing_or_blocked_evidence_closed():
    unknown = assess_external_paper_admission(
        position_baseline=None,
        readback_scope=PaperReadOnlyScopeStatus.SCOPED_INPUTS_CONSISTENT,
        balance_readback_passed=None,
        open_orders_empty=True,
        independent_fill_source_available=True,
    )
    assert unknown.status is ExternalPaperAdmissionStatus.UNKNOWN
    assert "POSITION_BASELINE_UNKNOWN" in unknown.reasons

    blocked = assess_external_paper_admission(
        position_baseline=PaperEvidenceAssessment(
            PaperEvidenceStatus.PASS, ()
        ),
        readback_scope=PaperReadOnlyScopeStatus.BLOCKED,
        balance_readback_passed=True,
        open_orders_empty=False,
        independent_fill_source_available=False,
    )
    assert blocked.status is ExternalPaperAdmissionStatus.BLOCKED
    assert "READBACK_SCOPE_BLOCKED" in blocked.reasons
    assert "OPEN_ORDERS_NOT_EMPTY" in blocked.reasons
