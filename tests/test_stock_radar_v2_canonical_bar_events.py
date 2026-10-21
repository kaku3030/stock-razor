"""Exporter -> existing poller -> real SQLite tests; no provider/model I/O."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.services.live_feed.canonical_snapshot_export import build_canonical_snapshot_export
from src.services.live_feed.futu_k1m_forming_accumulator import FormingMinuteBar
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar
from src.services.realtime_market_data import RealtimeMarketDataService
from src.services.stock_radar_v2.bar_event_ledger import RadarBarEventLedger
from src.services.stock_radar_v2.canonical_snapshot_worker import (
    CanonicalSnapshotRadarEvaluator, CanonicalSnapshotRadarWorker,
)

START = datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)
SHA = "a" * 40


def export(count=60, *, elapsed=5):
    observed = START + timedelta(minutes=count, seconds=elapsed)
    service = RealtimeMarketDataService(
        None, session_status_provider=lambda _: "regular",
        provider_health_provider=lambda: None, now=lambda: observed,
    )
    for index in range(count):
        end = START + timedelta(minutes=index + 1)
        service.ingest(closed_futu_minute_to_bar(FormingMinuteBar(
            symbol="US.AMD", start=end, open=100, high=101, low=99,
            close=100.5, volume=1000, turnover=100500, is_closed=True,
        ), received_at=end + timedelta(seconds=2)))
    body = build_canonical_snapshot_export(
        {"US.AMD": service.snapshot("US.AMD")}, runtime_instance_id="runtime-1",
        repo_sha=SHA, sequence=3, emitted_at_utc=observed,
        market_state_us="MORNING", cache_session_us="regular",
        delivery_mode="REALTIME", bar_closure="PROVEN",
    )
    return body, observed


def write(tmp_path, body):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def worker(ledger, observed):
    return CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA, event_ledger=ledger,
        evaluator=CanonicalSnapshotRadarEvaluator(now=lambda: observed),
    )


def test_existing_worker_persists_before_claim_and_dedupes_after_restart(tmp_path):
    body, observed = export()
    path = write(tmp_path, body)
    database = tmp_path / "events.sqlite"
    with RadarBarEventLedger(database) as ledger:
        poller = worker(ledger, observed)
        result = poller.poll_file(path)
        assert result.status == "PASS"
        assert result.bar_event_ingress.status == "RECORDED"
        assert result.bar_event_ingress.created_count == 2
        assert ledger.pending_count() == 2
        with RadarBarEventLedger(database) as reader:
            claim = reader.claim_next(worker_id="offline-consumer", now=observed)
            event = claim.event
            assert event.payload["signal_kind"] == "closed_bar_observation"
            assert event.payload["provider_id"] == "futu"
            assert event.payload["source_revision"] == SHA
            assert event.payload["live_trade"] is False
            assert event.payload["radar_admission"] == "BLOCKED"
            assert event.provenance["source_sequence"] == 3
        unchanged = poller.poll_file(path)
        assert unchanged.status == "UNCHANGED"
        assert unchanged.bar_event_ingress.created_count == 0
        assert unchanged.to_dict()["bar_event_ingress"]["status"] == "UNCHANGED"
        assert unchanged.can_confirm_signal is False
    body["runtime_instance_id"] = "runtime-2"
    body["sequence"] = 1
    body["emitted_at_utc"] = (observed + timedelta(seconds=10)).isoformat()
    with RadarBarEventLedger(database) as ledger:
        result = worker(ledger, observed + timedelta(seconds=10)).poll_file(write(tmp_path, body))
        assert result.bar_event_ingress.duplicate_count == 2
        assert result.bar_event_ingress.created_count == 0
        assert ledger.pending_count() == 2


def test_new_sequence_only_records_newly_closed_15m_not_old_1h(tmp_path):
    body, observed = export()
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        poller = worker(ledger, observed)
        poller.poll_file(write(tmp_path, body))
        body, later = export(count=75)
        body["sequence"] = 4
        poller._evaluator = CanonicalSnapshotRadarEvaluator(now=lambda: later)
        result = poller.poll_file(write(tmp_path, body))
        assert result.bar_event_ingress.created_count == 1
        assert ledger.pending_count() == 3


@pytest.mark.parametrize("mutation", [
    "unknown_delivery", "unproven_closure", "wrong_sha", "closed_session",
    "extended_session", "snapshot_stale", "snapshot_future", "fresh_export_old_bars",
    "future_export", "stale_export", "wrong_provider", "fallback", "snapshot_health",
    "missing_amount", "bad_turnover", "partial", "unclosed", "historical", "bar_health",
    "future_receipt", "wrong_source_time", "off_grid", "missing_grid",
])
def test_unqualified_source_never_inserts(tmp_path, mutation):
    body, observed = export()
    snap = body["symbols"]["US.AMD"]
    bar = snap["timeframes"]["15m"][-1]
    if mutation == "unknown_delivery":
        body["delivery_mode"] = "UNKNOWN"
    elif mutation == "unproven_closure":
        body["bar_closure"] = "UNPROVEN"
    elif mutation == "wrong_sha":
        body["repo_sha"] = "b" * 40
    elif mutation == "closed_session":
        body["market_state_us"] = "CLOSED"
    elif mutation == "extended_session":
        body["cache_session_us"] = "premarket"
    elif mutation == "snapshot_stale":
        snap["as_of_utc"] = START.isoformat()
    elif mutation == "snapshot_future":
        snap["as_of_utc"] = (observed + timedelta(seconds=1)).isoformat()
    elif mutation == "fresh_export_old_bars":
        observed += timedelta(minutes=10)
        body["emitted_at_utc"] = observed.isoformat()
        snap["as_of_utc"] = observed.isoformat()
    elif mutation == "future_export":
        body["emitted_at_utc"] = (observed + timedelta(seconds=1)).isoformat()
    elif mutation == "stale_export":
        observed += timedelta(minutes=3)
    elif mutation == "wrong_provider":
        bar["provider"] = "other"
    elif mutation == "fallback":
        snap["fallback_from"] = "other"
    elif mutation == "snapshot_health":
        snap["health"]["signal_permission"] = "watch_only"
    elif mutation == "missing_amount":
        bar["amount"] = None
    elif mutation == "bad_turnover":
        bar["amount"] = 1
    elif mutation == "partial":
        bar["is_complete"] = False
    elif mutation == "unclosed":
        bar["is_closed"] = False
    elif mutation == "historical":
        bar["quality_flags"] = ["HISTORICAL_QUERY"]
    elif mutation == "bar_health":
        bar["health"] = None
    elif mutation == "future_receipt":
        bar["received_at_utc"] = (observed + timedelta(seconds=1)).isoformat()
    elif mutation == "wrong_source_time":
        bar["source_timestamp_utc"] = START.isoformat()
    elif mutation == "off_grid":
        bar["bar_start_utc"] = (START + timedelta(minutes=46)).isoformat()
    elif mutation == "missing_grid":
        snap["timeframes"]["15m"].pop(0)
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = worker(ledger, observed).poll_file(write(tmp_path, body))
        assert result.status == "BLOCKED"
        assert ledger.pending_count() == 0
        assert result.can_confirm_signal is False


def test_queue_full_keeps_source_retryable_without_losing_events(tmp_path):
    body, observed = export()
    with RadarBarEventLedger(tmp_path / "events.sqlite", max_pending=1) as ledger:
        poller = worker(ledger, observed)
        path = write(tmp_path, body)
        blocked = poller.poll_file(path)
        assert blocked.status == "BLOCKED"
        assert "BAR_EVENT_QUEUE_FULL" in blocked.reasons
        assert ledger.pending_count() == 1  # each bar transaction is durable
        claim = ledger.claim_next(worker_id="offline-consumer", now=observed)
        ledger.acknowledge(claim.event.idempotency_key, lease_token=claim.lease_token, receipt_id="offline", now=observed)
        retried = poller.poll_file(path)
        assert retried.status == "PASS"
        assert retried.bar_event_ingress.created_count == 1
        assert retried.bar_event_ingress.duplicate_count == 1
        assert ledger.pending_count() == 1


def test_sqlite_failure_is_bounded_and_same_sequence_can_retry(tmp_path):
    body, observed = export()
    database = tmp_path / "events.sqlite"
    with RadarBarEventLedger(database) as ledger:
        poller = worker(ledger, observed)
        path = write(tmp_path, body)
        # Force a real transaction failure without waiting for SQLite's lock timeout.
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TRIGGER reject_event BEFORE INSERT ON stock_radar_bar_event_ledger BEGIN SELECT RAISE(ABORT, 'private path'); END")
        result = poller.poll_file(path)
        assert result.status == "BLOCKED"
        assert "BAR_EVENT_STORAGE_FAILED" in result.reasons
        assert "private path" not in json.dumps(result.to_dict())
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER reject_event")
        assert poller.poll_file(path).bar_event_ingress.created_count == 2


def test_unknown_calendar_does_not_accept_provider_session_claim(tmp_path, monkeypatch):
    from src.services.stock_radar_v2 import canonical_bar_events as ingress
    body, observed = export()
    monkeypatch.setattr(ingress, "infer_market_phase", lambda *_, **__: ingress.MarketPhase.UNKNOWN)
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = worker(ledger, observed).poll_file(write(tmp_path, body))
        assert result.bar_event_ingress.reasons == ("BAR_EVENT_SESSION_NOT_CONFIRMED",)
        assert ledger.pending_count() == 0


def test_default_worker_does_not_require_or_open_event_database(tmp_path):
    body, observed = export()
    body["bar_closure"] = "UNPROVEN"
    result = CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA,
        evaluator=CanonicalSnapshotRadarEvaluator(now=lambda: observed),
    ).poll_file(write(tmp_path, body))
    assert result.status == "PASS"
    assert result.bar_event_ingress is None
    assert list(tmp_path.glob("*.sqlite")) == []


@pytest.mark.parametrize("closed_at", [
    datetime(2026, 10, 17, 14, 30, 5, tzinfo=timezone.utc),  # Saturday
    datetime(2026, 12, 25, 15, 30, 5, tzinfo=timezone.utc),  # Christmas
])
def test_actual_exchange_calendar_rejects_false_active_session(tmp_path, closed_at):
    body, _ = export()
    body["emitted_at_utc"] = closed_at.isoformat()
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = worker(ledger, closed_at).poll_file(write(tmp_path, body))
        assert result.bar_event_ingress.reasons == ("BAR_EVENT_SESSION_NOT_CONFIRMED",)
        assert ledger.pending_count() == 0



def test_symbol_quality_flags_quarantine_one_symbol_without_blocking_valid_events(tmp_path):
    from copy import deepcopy

    body, observed = export()
    quarantined = deepcopy(body["symbols"]["US.AMD"])
    quarantined["symbol"] = "US.QQQ"
    for bars in quarantined["timeframes"].values():
        for bar in bars:
            bar["symbol"] = "US.QQQ"
    for timeframe in ("15m", "1h"):
        latest = quarantined["timeframes"][timeframe][-1]
        latest["quality_flags"] = ["VWAP_OUTSIDE_BAR_RANGE", "PARTIAL_TURNOVER"]
        latest["amount"] = None
    body["symbols"]["US.QQQ"] = quarantined

    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = worker(ledger, observed).poll_file(write(tmp_path, body))
        assert result.status == "PASS"
        assert result.bar_event_ingress.status == "PARTIAL"
        assert result.bar_event_ingress.created_count == 2
        assert ledger.pending_count() == 2
        assert any(
            reason.startswith("SYMBOL_BAR_QUARANTINED:US.QQQ:15m:")
            for reason in result.bar_event_ingress.reasons
        )
        assert result.to_dict()["admission_diagnostics"]["decision"] == "BLOCKED"



def test_symbol_health_quality_flag_quarantine_preserves_other_events(tmp_path):
    from copy import deepcopy

    body, observed = export()
    quarantined = deepcopy(body["symbols"]["US.AMD"])
    quarantined["symbol"] = "US.GLDM"
    quarantined["health"]["score"] = 49
    quarantined["health"]["signal_permission"] = "blocked"
    quarantined["health"]["quality_flags"] = ["VWAP_OUTSIDE_BAR_RANGE"]
    for bars in quarantined["timeframes"].values():
        for bar in bars:
            bar["symbol"] = "US.GLDM"
    body["symbols"]["US.GLDM"] = quarantined

    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = worker(ledger, observed).poll_file(write(tmp_path, body))
        assert result.status == "PASS"
        assert result.bar_event_ingress.status == "PARTIAL"
        assert result.bar_event_ingress.created_count == 4
        assert "SYMBOL_HEALTH_QUARANTINED:US.GLDM:VWAP_OUTSIDE_BAR_RANGE" in result.bar_event_ingress.reasons
        assert ledger.pending_count() == 4

def test_all_symbols_quarantined_still_blocks_without_inserting(tmp_path):
    body, observed = export()
    for timeframe in ("15m", "1h"):
        latest = body["symbols"]["US.AMD"]["timeframes"][timeframe][-1]
        latest["quality_flags"] = ["VWAP_OUTSIDE_BAR_RANGE", "PARTIAL_TURNOVER"]
        latest["amount"] = None

    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = worker(ledger, observed).poll_file(write(tmp_path, body))
        assert result.status == "BLOCKED"
        assert result.bar_event_ingress.status == "BLOCKED"
        assert "BAR_EVENT_NO_QUALIFIED_SYMBOLS" in result.bar_event_ingress.reasons
        assert ledger.pending_count() == 0

def test_all_symbols_validate_before_any_event_is_persisted(tmp_path):
    body, observed = export()
    from copy import deepcopy
    invalid = deepcopy(body["symbols"]["US.AMD"])
    invalid["symbol"] = "US.ZZZ"
    for bars in invalid["timeframes"].values():
        for bar in bars:
            bar["symbol"] = "US.ZZZ"
    invalid["timeframes"]["1h"][-1]["amount"] = None
    body["symbols"]["US.ZZZ"] = invalid
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = worker(ledger, observed).poll_file(write(tmp_path, body))
        assert result.status == "BLOCKED"
        assert ledger.pending_count() == 0


def test_changed_same_bar_facts_block_without_overwriting_original(tmp_path):
    body, observed = export()
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        poller = worker(ledger, observed)
        poller.poll_file(write(tmp_path, body))
        body["sequence"] = 4
        body["symbols"]["US.AMD"]["timeframes"]["15m"][-1]["close"] = 100.6
        result = poller.poll_file(write(tmp_path, body))
        assert result.status == "BLOCKED"
        assert result.bar_event_ingress.reasons == ("BAR_EVENT_FACT_CONFLICT",)
        assert ledger.pending_count() == 2


def test_unchanged_file_still_rechecks_source_age(tmp_path):
    body, observed = export()
    clock = [observed]
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        poller = CanonicalSnapshotRadarWorker(
            expected_repo_sha=SHA, event_ledger=ledger,
            evaluator=CanonicalSnapshotRadarEvaluator(now=lambda: clock[0]),
        )
        path = write(tmp_path, body)
        poller.poll_file(path)
        clock[0] += timedelta(minutes=3)
        result = poller.poll_file(path)
        assert result.status == "BLOCKED"
        assert result.reasons == ("SOURCE_EXPORT_STALE",)
        assert ledger.pending_count() == 2


@pytest.mark.parametrize("sequence", [True, 3.5, "3"])
def test_source_sequence_must_be_an_exact_integer_before_ledger_gate(tmp_path, sequence):
    body, observed = export()
    body["sequence"] = sequence
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = worker(ledger, observed).poll_file(write(tmp_path, body))
        assert result.status == "BLOCKED"
        assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)
        assert ledger.pending_count() == 0


def test_exporter_to_durable_ai_receipt_offline_vertical_slice(tmp_path):
    from src.llm.generation_backend import GenerationResult
    from src.services.stock_radar_v2.ai_event_consumer import RadarAIEventConsumer

    class OfflineBackend:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, generation_config, **kwargs):
            self.calls += 1
            facts = json.loads(prompt)
            return GenerationResult(
                text=json.dumps({"event_id": facts["event_id"], "assessment": "NO_SIGNAL", "evidence_fields": ["close"]}),
                model="offline", provider="offline", backend="offline",
                usage={"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
            )

    body, observed = export(count=75)
    database, backend = tmp_path / "events.sqlite", OfflineBackend()
    with RadarBarEventLedger(database) as ledger:
        result = worker(ledger, observed).poll_file(write(tmp_path, body))
        assert result.bar_event_ingress.created_count == 1
    # Reopen the actual persisted queue before the model seam is dispatched.
    with RadarBarEventLedger(database) as ledger:
        result = RadarAIEventConsumer(
            ledger, backend=backend, expected_source_sha=SHA, worker_id="offline-research",
            enabled=True, now=lambda: observed,
        ).poll_once()
        assert result.status == "COMPLETED"
        assert ledger.pending_count() == 0
        assert backend.calls == 1
        assert result.to_dict()["live_trade"] is False
