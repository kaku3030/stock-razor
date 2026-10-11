"""Only synthetic IDs/positions allowed; never real account data in CI."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.legacy_sim_inventory import LegacySimPosition
from src.services.sim_account_continuity import (
    SimAccountHostObservation, compare_local_cloud_sim,
)

NOW = datetime(2026, 10, 11, 13, tzinfo=timezone.utc)
POSITIONS = (
    LegacySimPosition("US.TEST", "LONG", Decimal("5")),
    LegacySimPosition("US.FAKE", "LONG", Decimal("8")),
)
WINDOWS = SimAccountHostObservation(
    account_id="123456", source="WINDOWS_LOCAL_OPEND",
    account_generation="local-session-1", observed_at_utc=NOW,
    account_mode="SIMULATE", market="US", authenticated=True,
    positions=POSITIONS,
)
AWS = replace(
    WINDOWS, source="AWS_OPEND_SSM", account_generation="cloud-session-2",
)


def compare(w=WINDOWS, a=AWS, **options):
    return compare_local_cloud_sim(w, a, now_utc=NOW, **options)


def test_matching_different_host_generations_still_fail_closed_for_ordering():
    result = compare()
    assert result.status == "MATCHED_FOR_REVIEW"
    assert result.same_account_id and result.same_positions
    assert result.position_count == 2
    assert not result.paper_auto_ready
    assert not result.broker_mutation_allowed
    assert "FILL" in result.reason


def test_account_mismatch_blocks_without_disclosing_actual_id():
    result = compare(a=replace(AWS, account_id="987654"))
    assert result.status == "BLOCKED"
    assert result.reason == "CROSS_HOST_SIM_ACCOUNT_ID_MISMATCH"
    assert "123456" not in str(result) and "987654" not in str(result)


def test_position_mismatch_and_differing_modes_block():
    data = (replace(POSITIONS[0], quantity=Decimal("6")), POSITIONS[1])
    assert compare(a=replace(AWS, positions=data)).reason == "CROSS_HOST_POSITION_MISMATCH"
    assert compare(a=replace(AWS, account_mode="REAL")).status == "BLOCKED"
    assert compare(a=replace(AWS, authenticated=False)).status == "BLOCKED"


def test_require_freshness_and_distinct_sources():
    assert compare(a=replace(
        AWS, observed_at_utc=NOW-timedelta(minutes=10),
    )).reason == "BROKER_READBACK_STALE_OR_FUTURE"
    assert compare(a=replace(AWS, source="WINDOWS_LOCAL_OPEND")).reason == (
        "OBSERVATION_SOURCE_MISMATCH"
    )


def test_cannot_treat_duplicate_position_rows_as_legacy_baseline():
    assert compare(a=replace(AWS, positions=POSITIONS+POSITIONS[:1])).reason == (
        "MALFORMED_READBACK_POSITIONS"
    )
