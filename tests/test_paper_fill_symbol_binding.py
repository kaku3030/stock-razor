"""Cross-instrument numeric coincidences are not independent fill evidence."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.external_simulator_readonly_preflight import (
    PaperEvidenceStatus, PaperPositionBaseline, PaperRealizedFillEvidence,
    assess_independent_realized_fill, assess_position_baseline,
)
from src.services.simulated_account_discovery import (
    AccountMode, SimulatedAccountDiscovery,
)

NOW = datetime(2026, 10, 11, 3, tzinfo=timezone.utc)
ACCOUNT = SimulatedAccountDiscovery("123456789", AccountMode.SIMULATE, "US", True, NOW)


def baseline(*, quantity, at, evidence):
    return PaperPositionBaseline(
        account_id=ACCOUNT.account_id, account_generation="generation-1",
        observed_at_utc=at, source="MOOMOO_OPEND_READONLY",
        readonly_evidence_id=evidence, position_quantity=Decimal(quantity),
        symbol="US.AMD",
    )


def fill(**changes):
    values = dict(
        fill_id="provider-fill-1", account_id=ACCOUNT.account_id,
        account_generation="generation-1",
        observed_at_utc=NOW - timedelta(seconds=1),
        source="MOOMOO_OPEND_READONLY", readonly_evidence_id="fill-read-1",
        side="BUY", filled_quantity=Decimal("2"),
        average_fill_price=Decimal("100"),
        cash_before=Decimal("1000"), cash_after=Decimal("799"),
        total_fees=Decimal("1"), symbol="US.AMD",
    )
    values.update(changes)
    return PaperRealizedFillEvidence(**values)


def test_cannot_pass_a_fill_using_baselines_from_another_instrument():
    before = baseline(quantity="4", at=NOW - timedelta(seconds=2), evidence="p1")
    after = baseline(quantity="6", at=NOW, evidence="p2")
    mismatch = assess_independent_realized_fill(
        before, after, fill(symbol="US.NVDA"), now_utc=NOW
    )
    assert mismatch.status == PaperEvidenceStatus.BLOCKED
    assert "REALIZED_FILL_SYMBOL_MISMATCH" in mismatch.reasons
    mixed_baselines = assess_independent_realized_fill(
        before, replace(after, symbol="US.TSLA"), fill(), now_utc=NOW
    )
    assert mixed_baselines.status == PaperEvidenceStatus.BLOCKED
    assert "POSITION_BASELINE_SYMBOL_MISMATCH" in mixed_baselines.reasons


def test_missing_instrument_binding_is_unknown_and_not_admissible():
    before = baseline(quantity="4", at=NOW - timedelta(seconds=2), evidence="p1")
    after = baseline(quantity="6", at=NOW, evidence="p2")
    result = assess_independent_realized_fill(
        before, after, replace(fill(), symbol=None), now_utc=NOW
    )
    assert result.status != PaperEvidenceStatus.PASS
    assert "REALIZED_FILL_SYMBOL_UNKNOWN" in result.reasons

    blank = assess_position_baseline(
        replace(before, symbol=None), ACCOUNT,
        expected_account_generation="generation-1",
        expected_source="MOOMOO_OPEND_READONLY",
        expected_readonly_evidence_id="p1",
        now_utc=NOW,
    )
    assert blank.status == PaperEvidenceStatus.UNKNOWN
    assert "POSITION_BASELINE_SYMBOL_UNKNOWN" in blank.reasons
