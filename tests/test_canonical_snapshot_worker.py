import inspect
import json
from datetime import datetime, timedelta, timezone

from data_provider.market_data_adapter import SignalPermission, evaluate_health
from src.services.live_feed.canonical_snapshot_export import build_canonical_snapshot_export
from src.services.live_feed.futu_k1m_forming_accumulator import FormingMinuteBar
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar
from src.services.realtime_market_data import RealtimeMarketDataService
from src.services.stock_radar_v2 import canonical_snapshot_worker as worker_module
from src.services.stock_radar_v2.canonical_snapshot_worker import (
    CanonicalSnapshotRadarEvaluator,
    CanonicalSnapshotRadarWorker,
    load_canonical_snapshot_payload,
)


START = datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)
SHA = "a" * 40
BLOCKED = evaluate_health(
    freshness=0,
    completeness=0,
    timestamp=0,
    provider=1,
    continuity=0,
    cross_check=0,
    quality_flags=("MISSING_BAR", "TIMESTAMP_SEMANTICS_UNVERIFIED"),
)


def service(now):
    return RealtimeMarketDataService(
        None,
        session_status_provider=lambda _market: "regular",
        provider_health_provider=lambda: BLOCKED,
        max_minutes=180,
        now=lambda: now,
    )


def add_minutes(svc, *, count=90, symbol="US.AMD"):
    eastern = timezone(timedelta(hours=-4))
    for index in range(count):
        start = START + timedelta(minutes=index)
        end = start + timedelta(minutes=1)
        provider_end = end.astimezone(eastern).replace(tzinfo=None)
        forming = FormingMinuteBar(
            symbol=symbol,
            start=provider_end,
            open=100.0 + index * 0.1,
            high=101.0 + index * 0.1,
            low=99.0 + index * 0.1,
            close=100.5 + index * 0.1,
            volume=1000.0 + index,
            turnover=100000.0 + index,
            is_closed=True,
        )
        svc.ingest(
            closed_futu_minute_to_bar(
                forming,
                received_at=end + timedelta(seconds=2),
            )
        )


def payload(*, count=90, emitted_at=None, cache_session="regular"):
    emitted = emitted_at or START + timedelta(minutes=count)
    svc = service(emitted)
    if count:
        add_minutes(svc, count=count)
    snapshot = svc.snapshot("US.AMD", as_of=emitted)
    result = build_canonical_snapshot_export(
        {"US.AMD": snapshot},
        runtime_instance_id="runtime-1",
        repo_sha=SHA,
        sequence=3,
        emitted_at_utc=emitted,
        market_state_us="MORNING" if cache_session == "regular" else "CLOSED",
        cache_session_us=cache_session,
    )
    return result


def write_payload(tmp_path, body):
    path = tmp_path / "canonical-market-snapshot.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_loader_reconstructs_all_canonical_timeframes_and_health():
    source = load_canonical_snapshot_payload(payload())
    assert source.repo_sha == SHA
    assert source.runtime_instance_id == "runtime-1"
    assert source.sequence == 3
    assert source.delivery_mode == "UNKNOWN"
    assert source.bar_closure == "UNPROVEN"
    assert source.radar_admission == "BLOCKED"
    assert source.live_trade is False

    snapshot = source.snapshots[0]
    assert snapshot.symbol == "US.AMD"
    assert len(snapshot.minute_bars) == 90
    assert len(snapshot.bars_5m) == 18
    assert len(snapshot.bars_15m) == 6
    assert len(snapshot.bars_1h) == 2
    assert snapshot.health.signal_permission is SignalPermission.NORMAL
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" not in snapshot.health.quality_flags


def test_evaluator_produces_research_only_state_from_canonical_snapshot(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    evaluator = CanonicalSnapshotRadarEvaluator(
        now=lambda: emitted + timedelta(seconds=30)
    )
    result = evaluator.evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )

    assert result.status == "PASS"
    assert result.research_only is True
    assert result.can_confirm_signal is False
    assert result.source_delivery_mode == "UNKNOWN"
    assert result.source_bar_closure == "UNPROVEN"
    assert result.source_radar_admission == "BLOCKED"
    assert result.source_live_trade is False
    assert len(result.symbols) == 1
    symbol = result.symbols[0]
    assert symbol.status == "RESEARCH_STATE"
    assert symbol.technical_state is not None
    assert symbol.technical_state.research_only is True
    assert symbol.technical_state.can_confirm_signal is False
    assert symbol.technical_state.signal_permission is SignalPermission.NORMAL
    assert "timestamp_semantics_unverified" not in symbol.technical_state.technical.risk_flags


def test_empty_canonical_cache_returns_no_bars_without_inventing_state(tmp_path):
    body = payload(count=0, emitted_at=START, cache_session="closed")
    evaluator = CanonicalSnapshotRadarEvaluator(now=lambda: START + timedelta(hours=2))
    result = evaluator.evaluate_file(write_payload(tmp_path, body), expected_repo_sha=SHA)

    assert result.status == "PASS"
    assert result.symbols[0].status == "NO_CANONICAL_BARS"
    assert result.symbols[0].technical_state is None
    assert result.symbols[0].reasons == ("NO_CANONICAL_BARS",)


def test_active_session_stale_export_is_blocked(tmp_path):
    emitted = START + timedelta(minutes=90)
    body = payload(emitted_at=emitted)
    evaluator = CanonicalSnapshotRadarEvaluator(
        max_active_age_seconds=120,
        now=lambda: emitted + timedelta(seconds=121),
    )
    result = evaluator.evaluate_file(write_payload(tmp_path, body), expected_repo_sha=SHA)

    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_EXPORT_STALE",)
    assert result.symbols == ()


def test_closed_session_old_export_is_not_promoted_but_can_be_researched(tmp_path):
    emitted = START + timedelta(minutes=90)
    body = payload(emitted_at=emitted, cache_session="closed")
    evaluator = CanonicalSnapshotRadarEvaluator(
        now=lambda: emitted + timedelta(hours=10)
    )
    result = evaluator.evaluate_file(write_payload(tmp_path, body), expected_repo_sha=SHA)

    assert result.status == "PASS"
    assert result.symbols[0].technical_state is not None
    assert result.symbols[0].technical_state.can_confirm_signal is False


def test_future_export_is_blocked(tmp_path):
    emitted = START + timedelta(minutes=90)
    body = payload(emitted_at=emitted)
    evaluator = CanonicalSnapshotRadarEvaluator(
        max_future_skew_seconds=5,
        now=lambda: emitted - timedelta(seconds=6),
    )
    result = evaluator.evaluate_file(write_payload(tmp_path, body), expected_repo_sha=SHA)

    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_EXPORT_FROM_FUTURE",)


def test_repo_sha_mismatch_is_blocked(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    evaluator = CanonicalSnapshotRadarEvaluator(now=lambda: emitted)
    result = evaluator.evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha="b" * 40,
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_REPO_SHA_MISMATCH",)


def test_malformed_timeframe_contract_is_blocked_without_crashing(tmp_path):
    body = payload()
    body["symbols"]["US.AMD"]["timeframes"]["15m"][0]["timeframe"] = "1h"
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    evaluator = CanonicalSnapshotRadarEvaluator(now=lambda: emitted)
    result = evaluator.evaluate_file(write_payload(tmp_path, body), expected_repo_sha=SHA)

    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)


def test_source_live_trade_true_is_rejected_at_contract_boundary(tmp_path):
    body = payload()
    body["live_trade"] = True
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    evaluator = CanonicalSnapshotRadarEvaluator(now=lambda: emitted)
    result = evaluator.evaluate_file(write_payload(tmp_path, body), expected_repo_sha=SHA)

    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)


def test_invalid_json_is_blocked_without_worker_crash(tmp_path):
    path = tmp_path / "canonical-market-snapshot.json"
    path.write_text("{not-json", encoding="utf-8")
    result = CanonicalSnapshotRadarEvaluator(now=lambda: START).evaluate_file(path)

    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:JSONDecodeError",)


def test_worker_has_no_provider_runtime_or_subscription_path():
    source = inspect.getsource(worker_module)
    assert "StockRadarProviderRuntime" not in source
    assert ".seed(" not in source
    assert ".subscribe(" not in source



def test_worker_skips_unchanged_sequence_after_successful_evaluation(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    worker = CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA,
        evaluator=CanonicalSnapshotRadarEvaluator(now=lambda: emitted),
    )
    path = write_payload(tmp_path, body)

    first = worker.poll_file(path)
    second = worker.poll_file(path)

    assert first.status == "PASS"
    assert second.status == "UNCHANGED"
    assert second.reasons == ("SOURCE_SEQUENCE_UNCHANGED",)
    assert len(second.symbols) == 1
    assert second.symbols[0].status == "RESEARCH_STATE"
    assert second.symbols[0].technical_state is not None
    assert second.symbols[0].technical_state.can_confirm_signal is False


def test_worker_rejects_sequence_regression_within_same_runtime(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    worker = CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA,
        evaluator=CanonicalSnapshotRadarEvaluator(now=lambda: emitted),
    )
    path = write_payload(tmp_path, body)
    assert worker.poll_file(path).status == "PASS"

    body["sequence"] = 2
    write_payload(tmp_path, body)
    result = worker.poll_file(path)

    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_SEQUENCE_REGRESSION",)


def test_worker_allows_sequence_reset_for_new_runtime(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    worker = CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA,
        evaluator=CanonicalSnapshotRadarEvaluator(now=lambda: emitted),
    )
    path = write_payload(tmp_path, body)
    assert worker.poll_file(path).status == "PASS"

    body["runtime_instance_id"] = "runtime-2"
    body["sequence"] = 1
    write_payload(tmp_path, body)
    result = worker.poll_file(path)

    assert result.status == "PASS"
    assert result.runtime_instance_id == "runtime-2"
    assert result.source_sequence == 1


def test_blocked_snapshot_does_not_advance_worker_sequence(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    clock = {"now": emitted - timedelta(seconds=6)}
    evaluator = CanonicalSnapshotRadarEvaluator(
        max_future_skew_seconds=5,
        now=lambda: clock["now"],
    )
    worker = CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA,
        evaluator=evaluator,
    )
    path = write_payload(tmp_path, body)

    first = worker.poll_file(path)
    assert first.status == "BLOCKED"
    assert first.reasons == ("SOURCE_EXPORT_FROM_FUTURE",)

    clock["now"] = emitted
    second = worker.poll_file(path)
    assert second.status == "PASS"


def test_worker_requires_exact_expected_repo_sha():
    try:
        CanonicalSnapshotRadarWorker(expected_repo_sha="short")
    except ValueError as exc:
        assert "exact 40-character" in str(exc)
    else:
        raise AssertionError("invalid worker repo SHA must fail")


def test_non_finite_ohlcv_is_rejected(tmp_path):
    body = payload()
    body["symbols"]["US.AMD"]["timeframes"]["1m"][0]["close"] = float("nan")
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )
    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)


def test_string_boolean_cannot_impersonate_closed_bar(tmp_path):
    body = payload()
    body["symbols"]["US.AMD"]["timeframes"]["1m"][0]["is_closed"] = "false"
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )
    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)


def test_empty_symbols_contract_is_rejected(tmp_path):
    body = payload()
    body["symbols"] = {}
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )
    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)


def test_evaluation_to_dict_is_json_serializable_and_remains_research_only(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )
    encoded = json.dumps(result.to_dict())
    decoded = json.loads(encoded)

    assert decoded["status"] == "PASS"
    assert decoded["research_only"] is True
    assert decoded["can_confirm_signal"] is False
    assert decoded["source_radar_admission"] == "BLOCKED"
    assert decoded["symbols"][0]["technical_state"]["research_only"] is True
    assert decoded["symbols"][0]["technical_state"]["can_confirm_signal"] is False


def test_unchanged_sequence_cannot_bypass_staleness_gate(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    clock = {"now": emitted}
    evaluator = CanonicalSnapshotRadarEvaluator(
        max_active_age_seconds=120,
        now=lambda: clock["now"],
    )
    worker = CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA,
        evaluator=evaluator,
    )
    path = write_payload(tmp_path, body)

    first = worker.poll_file(path)
    assert first.status == "PASS"

    clock["now"] = emitted + timedelta(seconds=121)
    second = worker.poll_file(path)

    assert second.status == "BLOCKED"
    assert second.reasons == ("SOURCE_EXPORT_STALE",)
    assert second.symbols == ()


def test_unchanged_sequence_cannot_bypass_future_clock_gate(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    clock = {"now": emitted}
    evaluator = CanonicalSnapshotRadarEvaluator(
        max_future_skew_seconds=5,
        now=lambda: clock["now"],
    )
    worker = CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA,
        evaluator=evaluator,
    )
    path = write_payload(tmp_path, body)

    assert worker.poll_file(path).status == "PASS"

    clock["now"] = emitted - timedelta(seconds=6)
    second = worker.poll_file(path)

    assert second.status == "BLOCKED"
    assert second.reasons == ("SOURCE_EXPORT_FROM_FUTURE",)



def test_proven_bar_closure_is_preserved_without_confirming_signal(tmp_path):
    body = payload()
    body["bar_closure"] = "PROVEN"
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )

    assert result.status == "PASS"
    assert result.source_bar_closure == "PROVEN"
    assert result.source_delivery_mode == "UNKNOWN"
    assert result.source_radar_admission == "BLOCKED"
    assert result.source_live_trade is False
    assert result.research_only is True
    assert result.can_confirm_signal is False
    assert result.symbols[0].technical_state is not None
    assert result.symbols[0].technical_state.can_confirm_signal is False


def test_invalid_source_bar_closure_is_rejected(tmp_path):
    body = payload()
    body["bar_closure"] = "MAYBE"
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )
    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)


def test_realtime_delivery_mode_is_preserved_without_confirming_signal(tmp_path):
    body = payload()
    body["delivery_mode"] = "REALTIME"
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )
    assert result.status == "PASS"
    assert result.source_delivery_mode == "REALTIME"
    assert result.source_radar_admission == "BLOCKED"
    assert result.source_live_trade is False
    assert result.research_only is True
    assert result.can_confirm_signal is False


def test_invalid_delivery_mode_is_rejected(tmp_path):
    body = payload()
    body["delivery_mode"] = "DELAYED"
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )
    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)


def test_non_blocked_radar_admission_is_rejected(tmp_path):
    body = payload()
    body["radar_admission"] = "PASS"
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )
    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_INVALID:CanonicalSnapshotContractError",)
