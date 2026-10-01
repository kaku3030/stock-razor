"""Minimal deterministic pattern engine for the Strategy Lab replay sandbox.

Only two bounded SHADOW patterns are implemented in this slice.  The module
emits immutable research events and snapshots; it never routes providers,
sends notifications, calls external services, or produces BUY/SELL actions.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Iterable

from .replay_contract import (
    EventRecord,
    InMemoryEventStore,
    PatternInstance,
    ReplayResult,
    Snapshot,
    SourceAuthorityResolver,
    UNKNOWN,
    aware_utc,
    stable_hash,
)


class ReplayBaselineEngine:
    THEME_IGNITION = "THEME_IGNITION_FAST"
    UNEXPLAINED = "UNEXPLAINED_ABNORMALITY"

    def __init__(
        self,
        rule_version: str = "run-a-a2-v0.1",
        *,
        source_authority_resolver: SourceAuthorityResolver | None = None,
        late_event_policy: str = "RECOMPUTE_SHADOW",
    ) -> None:
        self.rule_version = rule_version
        self.store = InMemoryEventStore(
            source_authority_resolver=source_authority_resolver,
            late_event_policy=late_event_policy,
        )
        self.instances: dict[str, PatternInstance] = {}
        self.missing_fields: dict[str, tuple[str, ...]] = {}
        self.side_effect_count = 0
        # SHADOW placeholders only; no production threshold authority is granted.
        self.theme_params = {
            "min_rs_jump": 15.0,
            "min_rvol": 2.0,
            "min_peer_count": 3,
            "min_breadth_delta": 0.15,
            "window_seconds": 90.0,
        }
        self.abnormal_params = {
            "min_abnormal_dimensions": 3,
            "gap_zscore": 2.0,
            "rvol": 2.0,
            "rs_jump": 10.0,
            "turnover_percentile": 90.0,
        }

    def ingest(self, event: EventRecord) -> str:
        return self.store.append(event)

    @staticmethod
    def _latest(events: list[EventRecord], event_type: str) -> EventRecord | None:
        matches = [event for event in events if event.event_type == event_type]
        if not matches:
            return None
        return max(matches, key=lambda event: (event.event_time, event.observed_at, event.event_id))

    def evaluate(self, decision_clock: datetime) -> tuple[PatternInstance, ...]:
        clock = aware_utc(decision_clock, "decision_clock")
        events = self.store.query_as_of(clock)
        # Diagnostics are an as-of view, never a sticky history of old UNKNOWNs.
        self.missing_fields = {}
        candidates = [
            *self._evaluate_theme_ignition(events),
            *self._evaluate_unexplained(events),
        ]
        for candidate in candidates:
            if candidate.dedup_key in self.instances:
                continue
            self.instances[candidate.dedup_key] = candidate
            self._append_pattern_event(candidate)
        return tuple(sorted(self.instances.values(), key=lambda item: item.pattern_instance_id))

    def _append_pattern_event(self, instance: PatternInstance) -> None:
        event = EventRecord(
            event_id=f"pattern:{instance.pattern_instance_id}",
            event_type="PATTERN_INSTANCE",
            entity_id=None,
            theme_id=None,
            occurred_at=instance.trigger_clock,
            event_time=instance.trigger_clock,
            published_at=instance.trigger_clock,
            available_at=instance.trigger_clock,
            observed_at=instance.trigger_clock,
            created_at=instance.trigger_clock,
            source_id="strategy_lab.replay_sandbox",
            payload={"pattern_instance": instance.canonical_payload()},
            parent_event_ids=instance.input_event_ids,
            trace_id=f"trace:{instance.pattern_instance_id}",
            source_kind="ENGINE_DERIVED",
        )
        status = self.store.append(event)
        if status not in {"ACCEPTED", "DUPLICATE"}:
            raise RuntimeError(f"derived pattern event append failed: {status}")

    def _build_instance(
        self,
        *,
        pattern_id: str,
        partition_key: str,
        input_events: list[EventRecord],
        severity: str,
        dedup_key: str,
        payload: dict[str, object],
    ) -> PatternInstance:
        ordered = sorted(input_events, key=lambda event: (event.observed_at, event.event_id))
        trigger_clock = max(event.observed_at for event in ordered)
        input_ids = tuple(event.event_id for event in ordered)
        identity_payload = {
            "pattern_id": pattern_id,
            "version": self.rule_version,
            "partition_key": partition_key,
            "trigger_clock": trigger_clock,
            "input_event_ids": input_ids,
            "dedup_key": dedup_key,
        }
        instance_id = f"pi-{stable_hash(identity_payload)[:24]}"
        return PatternInstance(
            pattern_id=pattern_id,
            version=self.rule_version,
            pattern_instance_id=instance_id,
            partition_key=partition_key,
            trigger_clock=trigger_clock,
            input_event_ids=input_ids,
            severity=severity,
            dedup_key=dedup_key,
            payload=payload,
        )

    def _evaluate_theme_ignition(self, events: list[EventRecord]) -> list[PatternInstance]:
        output: list[PatternInstance] = []
        themes = sorted({event.theme_id for event in events if event.theme_id})
        for theme in themes:
            scoped = [event for event in events if event.theme_id == theme]
            rs_event = self._latest(scoped, "LEADER_RS")
            rvol_event = self._latest(scoped, "LEADER_RVOL")
            breakout_event = self._latest(scoped, "LEADER_BREAKOUT")
            breadth_event = self._latest(scoped, "THEME_BREADTH")
            required_events = (rs_event, rvol_event, breakout_event, breadth_event)
            if any(event is None for event in required_events):
                missing = []
                if rs_event is None:
                    missing.append("rs_delta_short")
                if rvol_event is None:
                    missing.append("rvol")
                if breakout_event is None:
                    missing.append("structural_breakout_flag")
                if breadth_event is None:
                    missing.append("theme_breadth_delta")
                self.missing_fields[self.THEME_IGNITION] = tuple(sorted(missing))
                continue

            assert rs_event and rvol_event and breakout_event and breadth_event
            values = {
                "rs_delta_short": rs_event.payload.get("rs_delta_short", UNKNOWN),
                "rvol": rvol_event.payload.get("rvol", UNKNOWN),
                "structural_breakout_flag": breakout_event.payload.get(
                    "structural_breakout_flag", UNKNOWN
                ),
                "theme_breadth_delta": breadth_event.payload.get("theme_breadth_delta", UNKNOWN),
            }
            missing = tuple(
                sorted(name for name, value in values.items() if value == UNKNOWN or value is None)
            )
            if missing:
                self.missing_fields[self.THEME_IGNITION] = missing
                continue

            peer_events = [event for event in scoped if event.event_type == "PEER_ABNORMAL"]
            latest_by_peer: dict[str, EventRecord] = {}
            for event in peer_events:
                if event.entity_id:
                    prior = latest_by_peer.get(event.entity_id)
                    if prior is None or (event.event_time, event.event_id) > (
                        prior.event_time,
                        prior.event_id,
                    ):
                        latest_by_peer[event.entity_id] = event
            if len(latest_by_peer) < self.theme_params["min_peer_count"]:
                continue

            evidence = [rs_event, rvol_event, breakout_event, breadth_event, *latest_by_peer.values()]
            event_times = [event.event_time for event in evidence]
            window_seconds = (max(event_times) - min(event_times)).total_seconds()
            meets = (
                float(values["rs_delta_short"]) >= self.theme_params["min_rs_jump"]
                and float(values["rvol"]) >= self.theme_params["min_rvol"]
                and values["structural_breakout_flag"] is True
                and float(values["theme_breadth_delta"]) >= self.theme_params["min_breadth_delta"]
                and window_seconds <= self.theme_params["window_seconds"]
            )
            if not meets:
                continue
            dedup_key = f"{self.THEME_IGNITION}:{theme}:{self.rule_version}"
            output.append(
                self._build_instance(
                    pattern_id=self.THEME_IGNITION,
                    partition_key=f"THEME:{theme}",
                    input_events=evidence,
                    severity="HIGH",
                    dedup_key=dedup_key,
                    payload={
                        "theme_id": theme,
                        "diffusion_count": len(latest_by_peer),
                        "entry_gate": "CLOSED",
                    },
                )
            )
        return output

    def _evaluate_unexplained(self, events: list[EventRecord]) -> list[PatternInstance]:
        output: list[PatternInstance] = []
        abnormal_events = sorted(
            (event for event in events if event.event_type == "MARKET_ABNORMALITY"),
            key=lambda event: (event.observed_at, event.event_id),
        )
        for event in abnormal_events:
            payload = event.payload
            grounded = payload.get("grounded_catalyst_present", UNKNOWN)
            if grounded == UNKNOWN or grounded is None:
                self.missing_fields[self.UNEXPLAINED] = ("grounded_catalyst_present",)
                continue
            dimensions = 0
            thresholds = (
                ("gap_zscore", "gap_zscore"),
                ("rvol", "rvol"),
                ("rs_jump", "rs_jump"),
                ("turnover_percentile", "turnover_percentile"),
            )
            for field, param in thresholds:
                value = payload.get(field, UNKNOWN)
                if value != UNKNOWN and value is not None and float(value) >= self.abnormal_params[param]:
                    dimensions += 1
            if payload.get("breadth_anomaly") is True:
                dimensions += 1
            if dimensions < self.abnormal_params["min_abnormal_dimensions"] or grounded is not False:
                continue
            entity = event.entity_id or "UNKNOWN_ENTITY"
            dedup_key = f"{self.UNEXPLAINED}:{entity}:{self.rule_version}"
            output.append(
                self._build_instance(
                    pattern_id=self.UNEXPLAINED,
                    partition_key=f"SYMBOL:{entity}",
                    input_events=[event],
                    severity="MEDIUM",
                    dedup_key=dedup_key,
                    payload={
                        "abnormal_dimensions": dimensions,
                        "rumor_only": bool(payload.get("rumor_only", False)),
                        "watch_status": self.UNEXPLAINED,
                        "promotion_ready": False,
                        "entry_gate": "CLOSED",
                    },
                )
            )
        return output

    def snapshot(self, decision_clock: datetime, data_version: str = "synthetic-a2-v0.1") -> Snapshot:
        clock = aware_utc(decision_clock, "decision_clock")
        instances = self.evaluate(clock)
        events = self.store.query_as_of(clock)
        accepted_ids = tuple(event.event_id for event in events)
        accepted_set = set(accepted_ids)
        trace_complete = all(set(instance.input_event_ids).issubset(accepted_set) for instance in instances)
        audit_status = "COMPLETE" if trace_complete else "AUDIT_INCOMPLETE"
        unknown_bitmap = tuple(
            sorted((pattern_id, fields) for pattern_id, fields in self.missing_fields.items())
        )
        hash_payload = {
            "decision_clock": clock,
            "accepted_event_ids": accepted_ids,
            "event_checksums": tuple((event.event_id, event.checksum) for event in events),
            "pattern_instances": tuple(instance.canonical_payload() for instance in instances),
            "rule_version": self.rule_version,
            "data_version": data_version,
            "audit_status": audit_status,
            "unknown_bitmap": unknown_bitmap,
        }
        canonical_hash = stable_hash(hash_payload)
        return Snapshot(
            snapshot_id=f"snap-{canonical_hash[:24]}",
            decision_clock=clock,
            accepted_event_ids=accepted_ids,
            pattern_instances=instances,
            rule_version=self.rule_version,
            data_version=data_version,
            audit_status=audit_status,
            unknown_bitmap=unknown_bitmap,
            canonical_hash=canonical_hash,
        )


def _delivery_late_count(events: list[EventRecord]) -> int:
    count = 0
    max_seen: datetime | None = None
    for event in events:
        if max_seen is not None and event.observed_at < max_seen:
            count += 1
        if max_seen is None or event.observed_at > max_seen:
            max_seen = event.observed_at
    return count


def replay(
    events: Iterable[EventRecord],
    decision_clock: datetime,
    rule_version: str = "run-a-a2-v0.1",
    *,
    source_authority_resolver: SourceAuthorityResolver | None = None,
) -> ReplayResult:
    """Rebuild the incremental decision path as it would have evolved then."""

    clock = aware_utc(decision_clock, "decision_clock")
    supplied = list(events)
    persisted_derived = {
        event.event_id: event
        for event in supplied
        if event.source_kind == "ENGINE_DERIVED" and event.observed_at <= clock
    }
    eligible_raw = [
        (position, event)
        for position, event in enumerate(supplied)
        if event.source_kind != "ENGINE_DERIVED" and event.observed_at <= clock
    ]
    eligible_raw.sort(key=lambda pair: (pair[1].observed_at, pair[1].event_id, pair[0]))

    engine = ReplayBaselineEngine(
        rule_version=rule_version,
        source_authority_resolver=source_authority_resolver,
    )
    for _, event in eligible_raw:
        if engine.ingest(event) == "ACCEPTED":
            engine.evaluate(event.observed_at)
    snapshot = engine.snapshot(clock)

    regenerated = {
        event.event_id: event
        for event in engine.store.query_as_of(clock)
        if event.source_kind == "ENGINE_DERIVED"
    }
    mismatches = 0
    for event_id, persisted in persisted_derived.items():
        rebuilt = regenerated.get(event_id)
        if rebuilt is None or rebuilt.checksum != persisted.checksum:
            mismatches += 1
    if persisted_derived:
        mismatches += len(set(regenerated) - set(persisted_derived))

    return ReplayResult(
        snapshot=snapshot,
        duplicate_count=engine.store.duplicate_count,
        late_count=_delivery_late_count(supplied),
        rejected_count=engine.store.rejected_count,
        late_dropped_count=engine.store.late_dropped_count,
        derived_replay_mismatch_count=mismatches,
        side_effect_count=engine.side_effect_count,
    )
