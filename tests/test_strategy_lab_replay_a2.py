from dataclasses import replace
from datetime import datetime, timedelta, timezone
import random

import pytest

from src.services.strategy_lab.replay_baseline import ReplayBaselineEngine, replay
from src.services.strategy_lab.replay_contract import EventRecord, InMemoryEventStore, stable_hash
from src.services.strategy_lab.replay_source_authority import resolve_cn_replay_source

UTC = timezone.utc
BASE = datetime(2026, 9, 10, 1, 0, 0, tzinfo=UTC)
DECISION = BASE + timedelta(seconds=80)


def ev(
    event_id,
    event_type,
    *,
    sec,
    entity=None,
    theme="AI",
    payload=None,
    observed_sec=None,
    source_kind="SYNTHETIC",
    source_token=None,
    endpoint_id=None,
    market=None,
):
    event_time = BASE + timedelta(seconds=sec)
    observed_at = BASE + timedelta(seconds=sec if observed_sec is None else observed_sec)
    return EventRecord(
        event_id=event_id,
        event_type=event_type,
        entity_id=entity,
        theme_id=theme,
        occurred_at=event_time,
        event_time=event_time,
        published_at=event_time,
        available_at=observed_at,
        observed_at=observed_at,
        created_at=observed_at,
        source_id="fixture://strategy-lab/replay-a2",
        payload=payload or {},
        source_kind=source_kind,
        source_token=source_token,
        endpoint_id=endpoint_id,
        market=market,
    )


def theme_positive():
    return [
        ev("rs", "LEADER_RS", sec=1, entity="LEADER", payload={"rs_delta_short": 18.0}),
        ev("rv", "LEADER_RVOL", sec=5, entity="LEADER", payload={"rvol": 2.6}),
        ev(
            "bo",
            "LEADER_BREAKOUT",
            sec=10,
            entity="LEADER",
            payload={"structural_breakout_flag": True},
        ),
        ev("p1", "PEER_ABNORMAL", sec=20, entity="P1"),
        ev("p2", "PEER_ABNORMAL", sec=30, entity="P2"),
        ev("p3", "PEER_ABNORMAL", sec=40, entity="P3"),
        ev("br", "THEME_BREADTH", sec=50, payload={"theme_breadth_delta": 0.22}),
    ]


def unexplained(*, rumor=False, grounded=False):
    return [
        ev(
            "abn-r" if rumor else "abn",
            "MARKET_ABNORMALITY",
            sec=20,
            entity="600000.SH",
            theme=None,
            payload={
                "gap_zscore": 2.8,
                "rvol": 3.1,
                "rs_jump": 14.0,
                "turnover_percentile": 95.0,
                "breadth_anomaly": False,
                "grounded_catalyst_present": grounded,
                "rumor_only": rumor,
                "source_truth": True,
                "claim_truth": "UNVERIFIED" if rumor else "NONE",
            },
        )
    ]


def pattern(result, pattern_id):
    return [item for item in result.snapshot.pattern_instances if item.pattern_id == pattern_id]


def test_theme_ignition_positive_emits_one_closed_gate_instance():
    result = replay(theme_positive(), DECISION)
    matches = pattern(result, ReplayBaselineEngine.THEME_IGNITION)
    assert len(matches) == 1
    assert matches[0].payload["diffusion_count"] == 3
    assert matches[0].payload["entry_gate"] == "CLOSED"
    assert result.snapshot.audit_status == "COMPLETE"


def test_cross_theme_peers_cannot_manufacture_breadth():
    events = theme_positive()
    events[4] = replace(events[4], theme_id="ROBOTICS", checksum="")
    events[5] = replace(events[5], theme_id="CHIPS", checksum="")
    assert pattern(replay(events, DECISION), ReplayBaselineEngine.THEME_IGNITION) == []


def test_duplicate_input_does_not_change_effective_snapshot():
    base = replay(theme_positive(), DECISION)
    duplicated = replay([*theme_positive(), theme_positive()[3]], DECISION)
    assert duplicated.duplicate_count == 1
    assert duplicated.snapshot.canonical_hash == base.snapshot.canonical_hash


def test_conflicting_duplicate_event_id_fails_loud():
    original = theme_positive()[0]
    conflict = replace(original, payload={"rs_delta_short": 99.0}, checksum="")
    store = InMemoryEventStore()
    assert store.append(original) == "ACCEPTED"
    with pytest.raises(ValueError, match="event_id collision with conflicting checksum"):
        store.append(conflict)


def test_conflicting_duplicate_event_id_fails_loud_in_any_delivery_order():
    original = theme_positive()[0]
    conflict = replace(original, payload={"rs_delta_short": 99.0}, checksum="")
    with pytest.raises(ValueError, match="event_id collision with conflicting checksum"):
        replay([original, conflict], DECISION)
    with pytest.raises(ValueError, match="event_id collision with conflicting checksum"):
        replay([conflict, original], DECISION)


def test_unknown_required_field_is_preserved_and_blocks_match():
    events = theme_positive()
    events[-1] = replace(events[-1], payload={}, checksum="")
    result = replay(events, DECISION)
    assert pattern(result, ReplayBaselineEngine.THEME_IGNITION) == []
    assert (
        ReplayBaselineEngine.THEME_IGNITION,
        ("theme_breadth_delta",),
    ) in result.snapshot.unknown_bitmap


def test_unexplained_abnormality_is_watch_only_and_entry_closed():
    result = replay(unexplained(), DECISION)
    matches = pattern(result, ReplayBaselineEngine.UNEXPLAINED)
    assert len(matches) == 1
    assert matches[0].payload["watch_status"] == ReplayBaselineEngine.UNEXPLAINED
    assert matches[0].payload["promotion_ready"] is False
    assert matches[0].payload["entry_gate"] == "CLOSED"


def test_real_source_reporting_rumor_does_not_become_grounded_catalyst():
    result = replay(unexplained(rumor=True), DECISION)
    matches = pattern(result, ReplayBaselineEngine.UNEXPLAINED)
    assert len(matches) == 1
    assert matches[0].payload["rumor_only"] is True
    assert matches[0].payload["entry_gate"] == "CLOSED"


def test_grounded_catalyst_blocks_unexplained_pattern():
    assert pattern(
        replay(unexplained(grounded=True), DECISION),
        ReplayBaselineEngine.UNEXPLAINED,
    ) == []


def test_future_masking_invariance():
    base = replay(theme_positive(), DECISION)
    future = ev(
        "future",
        "MARKET_ABNORMALITY",
        sec=120,
        observed_sec=120,
        entity="FUTURE",
        theme=None,
        payload={
            "gap_zscore": 9.0,
            "rvol": 9.0,
            "rs_jump": 40.0,
            "turnover_percentile": 99.0,
            "grounded_catalyst_present": False,
        },
    )
    masked = replay([*theme_positive(), future], DECISION)
    assert future.event_id not in masked.snapshot.accepted_event_ids
    assert masked.snapshot.canonical_hash == base.snapshot.canonical_hash


def test_backfill_observed_later_cannot_rewrite_old_snapshot():
    base = replay(theme_positive(), DECISION)
    correction = ev(
        "future-correction",
        "THEME_BREADTH",
        sec=45,
        observed_sec=140,
        payload={"theme_breadth_delta": -0.5},
    )
    revised = replay([*theme_positive(), correction], DECISION)
    assert revised.snapshot.canonical_hash == base.snapshot.canonical_hash


def test_observed_at_cannot_precede_available_at():
    with pytest.raises(ValueError, match="observed_at cannot precede available_at"):
        EventRecord(
            event_id="bad-time",
            event_type="X",
            entity_id=None,
            theme_id=None,
            occurred_at=BASE,
            event_time=BASE,
            published_at=BASE,
            available_at=BASE + timedelta(seconds=2),
            observed_at=BASE + timedelta(seconds=1),
            created_at=BASE + timedelta(seconds=2),
            source_id="fixture",
            payload={},
        )


def test_deterministic_replay_is_100_of_100_identical():
    hashes = [replay(theme_positive(), DECISION).snapshot.canonical_hash for _ in range(100)]
    assert len(set(hashes)) == 1


def test_live_incremental_path_equals_canonical_replay():
    engine = ReplayBaselineEngine()
    for event in sorted(theme_positive(), key=lambda item: (item.observed_at, item.event_id)):
        assert engine.ingest(event) == "ACCEPTED"
        engine.evaluate(event.observed_at)
    live = engine.snapshot(DECISION)
    rebuilt = replay(theme_positive(), DECISION).snapshot
    assert rebuilt.canonical_hash == live.canonical_hash
    assert rebuilt.pattern_instances == live.pattern_instances


def test_delivery_order_randomization_keeps_canonical_replay_hash():
    expected = replay(theme_positive(), DECISION).snapshot.canonical_hash
    rng = random.Random(20260910)
    for _ in range(100):
        shuffled = theme_positive()
        rng.shuffle(shuffled)
        assert replay(shuffled, DECISION).snapshot.canonical_hash == expected


def test_pattern_identity_is_stable_across_later_snapshot_clock():
    first = pattern(replay(theme_positive(), DECISION), ReplayBaselineEngine.THEME_IGNITION)[0]
    later = pattern(
        replay(theme_positive(), DECISION + timedelta(seconds=10)),
        ReplayBaselineEngine.THEME_IGNITION,
    )[0]
    assert later.pattern_instance_id == first.pattern_instance_id
    assert later.trigger_clock == first.trigger_clock


def test_event_payload_is_deeply_immutable():
    event = theme_positive()[0]
    with pytest.raises(TypeError):
        event.payload["rs_delta_short"] = 999


def test_nearby_float_values_do_not_collapse_hash():
    assert stable_hash({"x": 1.2345678901234}) != stable_hash({"x": 1.2345678901235})


def test_rule_version_changes_hash_without_mutating_prior_result():
    v1 = replay(theme_positive(), DECISION, rule_version="run-a-a2-v0.1")
    original = v1.snapshot.canonical_hash
    v2 = replay(theme_positive(), DECISION, rule_version="run-a-a2-v0.2")
    assert v2.snapshot.canonical_hash != original
    assert v1.snapshot.canonical_hash == original


def test_persisted_derived_log_replays_without_counting_derived_as_input():
    engine = ReplayBaselineEngine()
    for event in theme_positive():
        engine.ingest(event)
    original = engine.snapshot(DECISION)
    persisted = list(engine.store.events)
    rebuilt = replay(persisted, DECISION)
    assert rebuilt.duplicate_count == 0
    assert rebuilt.derived_replay_mismatch_count == 0
    assert rebuilt.snapshot.canonical_hash == original.canonical_hash


def test_persisted_derived_tamper_is_detected():
    engine = ReplayBaselineEngine()
    for event in theme_positive():
        engine.ingest(event)
    engine.snapshot(DECISION)
    persisted = list(engine.store.events)
    index = next(i for i, item in enumerate(persisted) if item.source_kind == "ENGINE_DERIVED")
    derived = persisted[index]
    payload = dict(derived.payload)
    payload["tampered"] = True
    persisted[index] = replace(derived, payload=payload, checksum="")
    assert replay(persisted, DECISION).derived_replay_mismatch_count == 1


def test_late_drop_policy_fails_closed_without_rewriting_store():
    store = InMemoryEventStore(late_event_policy="DROP")
    newer = ev("newer", "X", sec=50)
    older = ev("older", "X", sec=40)
    assert store.append(newer) == "ACCEPTED"
    before = tuple(item.event_id for item in store.query_as_of(DECISION))
    assert store.append(older) == "LATE_DROPPED"
    after = tuple(item.event_id for item in store.query_as_of(DECISION))
    assert before == after == ("newer",)
    assert store.late_count == 1
    assert store.late_dropped_count == 1


def test_dropped_late_event_id_still_rejects_conflicting_reuse():
    store = InMemoryEventStore(late_event_policy="DROP")
    assert store.append(ev("newer", "X", sec=50)) == "ACCEPTED"
    dropped = ev("older", "X", sec=40)
    assert store.append(dropped) == "LATE_DROPPED"
    conflict = replace(dropped, payload={"changed": True}, checksum="")
    with pytest.raises(ValueError, match="event_id collision with conflicting checksum"):
        store.append(conflict)


def test_unknown_late_policy_fails_loud():
    with pytest.raises(ValueError, match="late_event_policy"):
        InMemoryEventStore(late_event_policy="SILENT_REWRITE")


def provider_event(*, source_token="akshare_em", endpoint_id="akshare.eastmoney_intraday", market="cn"):
    return replace(
        theme_positive()[0],
        source_kind="PROVIDER",
        source_token=source_token,
        endpoint_id=endpoint_id,
        market=market,
        checksum="",
    )


def test_provider_event_fails_closed_without_authority_resolver():
    store = InMemoryEventStore()
    assert store.append(provider_event()) == "REJECTED_SOURCE_AUTHORITY"


def test_a1_extension_resolves_via_a0_identity_without_second_registry():
    store = InMemoryEventStore(source_authority_resolver=resolve_cn_replay_source)
    assert store.append(provider_event()) == "ACCEPTED"
    stored = store.query_as_of(DECISION)[0]
    assert stored.source_adapter_id == "akshare"
    assert stored.source_upstream_lineage_id == "eastmoney"
    assert stored.source_authority_ref.startswith("a-share-a0-a1:")


@pytest.mark.parametrize(
    "event",
    [
        provider_event(source_token="unknown_provider"),
        provider_event(endpoint_id="akshare.sina_spot"),
        provider_event(market="us"),
    ],
)
def test_invalid_repository_source_binding_fails_closed(event):
    store = InMemoryEventStore(source_authority_resolver=resolve_cn_replay_source)
    assert store.append(event) == "REJECTED_SOURCE_AUTHORITY"


def test_non_provider_cannot_smuggle_authority_metadata():
    event = replace(
        theme_positive()[0],
        source_authority_ref="forged",
        source_adapter_id="forged",
        source_upstream_lineage_id="forged",
        checksum="",
    )
    assert InMemoryEventStore().append(event) == "REJECTED_SOURCE_AUTHORITY"


def test_replay_has_no_side_effects():
    assert replay(theme_positive(), DECISION).side_effect_count == 0
