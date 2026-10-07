import inspect
import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from data_provider.market_data_adapter import SignalPermission, evaluate_health
from src.services.live_feed.canonical_snapshot_export import build_canonical_snapshot_export
from src.services.live_feed.futu_k1m_forming_accumulator import FormingMinuteBar
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar
from src.services.realtime_market_data import RealtimeMarketDataService
from src.services.options_intelligence import (
    OptionGexObservation,
    build_gamma_profile,
    build_gex_evidence,
    build_options_intelligence_packet,
    qualify_options_clock_alignment,
    qualify_quote_freshness,
)
from src.services.options_intelligence.gamma_profile import apply_gamma_profile
from src.services.options_intelligence.gex import OptionType
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


def payload(
    *,
    count=90,
    emitted_at=None,
    cache_session="regular",
    market_state=None,
    delivery_mode="UNKNOWN",
    bar_closure="UNPROVEN",
):
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
        market_state_us=(
            market_state
            if market_state is not None
            else ("MORNING" if cache_session == "regular" else "CLOSED")
        ),
        cache_session_us=cache_session,
        delivery_mode=delivery_mode,
        bar_closure=bar_closure,
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


def test_admission_diagnostics_explain_blocked_source_prerequisites(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )

    diagnostics = result.admission_diagnostics()
    assert diagnostics["decision"] == "BLOCKED"
    assert diagnostics["promotion_authorized"] is False
    assert diagnostics["minimum_source_prerequisites_met"] is False
    assert diagnostics["delivery_mode_realtime"] is False
    assert diagnostics["bar_closure_proven"] is False
    assert diagnostics["research_state_symbols"] == ["US.AMD"]
    assert diagnostics["no_canonical_bar_symbols"] == []
    assert diagnostics["normal_health_symbols"] == ["US.AMD"]
    assert diagnostics["non_normal_health_symbols"] == []
    assert diagnostics["reasons"] == [
        "SOURCE_DELIVERY_MODE_NOT_REALTIME",
        "SOURCE_BAR_CLOSURE_UNPROVEN",
        "PROMOTION_NOT_AUTHORIZED",
    ]
    assert result.source_radar_admission == "BLOCKED"
    assert result.source_live_trade is False
    assert result.can_confirm_signal is False


def test_minimum_source_prerequisites_do_not_authorize_radar_promotion(tmp_path):
    body = payload(delivery_mode="REALTIME", bar_closure="PROVEN")
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )

    diagnostics = result.admission_diagnostics()
    assert diagnostics["minimum_source_prerequisites_met"] is True
    assert diagnostics["decision"] == "BLOCKED"
    assert diagnostics["promotion_authorized"] is False
    assert diagnostics["reasons"] == ["PROMOTION_NOT_AUTHORIZED"]
    assert result.source_radar_admission == "BLOCKED"
    assert result.source_live_trade is False
    assert result.research_only is True
    assert result.can_confirm_signal is False


def test_source_prerequisites_cannot_launder_empty_canonical_cache(tmp_path):
    body = payload(
        count=0,
        emitted_at=START,
        cache_session="closed",
        delivery_mode="REALTIME",
        bar_closure="PROVEN",
    )
    result = CanonicalSnapshotRadarEvaluator(now=lambda: START).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )

    diagnostics = result.admission_diagnostics()
    assert diagnostics["minimum_source_prerequisites_met"] is True
    assert diagnostics["no_canonical_bar_symbols"] == ["US.AMD"]
    assert diagnostics["normal_health_symbols"] == []
    assert diagnostics["decision"] == "BLOCKED"
    assert diagnostics["promotion_authorized"] is False
    assert diagnostics["reasons"] == [
        "SYMBOLS_WITHOUT_CANONICAL_BARS",
        "PROMOTION_NOT_AUTHORIZED",
    ]


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


def test_after_hours_end_old_export_can_be_researched_without_realtime_promotion(tmp_path):
    emitted = START + timedelta(minutes=90)
    body = payload(
        emitted_at=emitted,
        cache_session="afterhours",
        market_state="AFTER_HOURS_END",
        delivery_mode="REALTIME",
        bar_closure="UNPROVEN",
    )
    evaluator = CanonicalSnapshotRadarEvaluator(
        max_active_age_seconds=120,
        now=lambda: emitted + timedelta(hours=10),
    )
    result = evaluator.evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )

    assert result.status == "PASS"
    assert result.source_delivery_mode == "REALTIME"
    assert result.source_bar_closure == "UNPROVEN"
    assert result.research_only is True
    assert result.can_confirm_signal is False
    assert result.symbols[0].status == "RESEARCH_STATE"
    assert result.symbols[0].technical_state is not None
    assert result.symbols[0].technical_state.can_confirm_signal is False
    assert result.admission_diagnostics()["decision"] == "BLOCKED"
    assert "SOURCE_BAR_CLOSURE_UNPROVEN" in result.admission_diagnostics()["reasons"]


def test_regular_market_state_still_blocks_stale_export_even_if_cache_session_is_wrong(tmp_path):
    emitted = START + timedelta(minutes=90)
    body = payload(
        emitted_at=emitted,
        cache_session="closed",
        market_state="AFTERNOON",
    )
    evaluator = CanonicalSnapshotRadarEvaluator(
        max_active_age_seconds=120,
        now=lambda: emitted + timedelta(seconds=121),
    )
    result = evaluator.evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_EXPORT_STALE",)
    assert result.symbols == ()


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
    assert decoded["admission_diagnostics"]["decision"] == "BLOCKED"
    assert decoded["admission_diagnostics"]["promotion_authorized"] is False
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


def test_evaluator_uses_validated_daily_context_when_supplied(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    daily = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-04-01") + pd.Timedelta(days=index),
                "open": 80.0 + index * 0.2,
                "high": 82.0 + index * 0.2,
                "low": 79.0 + index * 0.2,
                "close": 81.0 + index * 0.2,
                "volume": 100000.0 + index,
            }
            for index in range(120)
        ]
    )
    result = CanonicalSnapshotRadarEvaluator(now=lambda: emitted).evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
        daily_frames={"US.AMD": daily},
    )

    assert result.status == "PASS"
    state = result.symbols[0].technical_state
    assert state is not None
    assert state.research_only is True
    assert state.can_confirm_signal is False
    assert state.technical.daily.quality.status != "missing"
    assert state.technical.daily.quality.bars == 120
    assert "1d_data_missing" not in state.technical.daily.quality.warnings


def test_worker_preserves_daily_context_on_unchanged_sequence(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    daily = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-04-01") + pd.Timedelta(days=index),
                "open": 90.0 + index * 0.1,
                "high": 91.0 + index * 0.1,
                "low": 89.0 + index * 0.1,
                "close": 90.5 + index * 0.1,
                "volume": 1000.0 + index,
            }
            for index in range(120)
        ]
    )
    worker = CanonicalSnapshotRadarWorker(
        expected_repo_sha=SHA,
        evaluator=CanonicalSnapshotRadarEvaluator(now=lambda: emitted),
    )
    path = write_payload(tmp_path, body)
    first = worker.poll_file(path, daily_frames={"US.AMD": daily})
    second = worker.poll_file(path, daily_frames={"US.AMD": daily})

    assert first.status == "PASS"
    assert second.status == "UNCHANGED"
    assert second.symbols[0].technical_state is not None
    assert second.symbols[0].technical_state.technical.daily.quality.bars == 120


def _qualified_options_packet(as_of, *, underlying="AMD", oi_known=True):
    oi_asof = as_of if oi_known else None
    rows = [
        OptionGexObservation(
            contract_symbol=f"{underlying}-C105",
            underlying_symbol=underlying,
            option_type=OptionType.CALL,
            strike=105.0,
            expiration=(as_of + timedelta(days=10)).date(),
            open_interest=1000,
            gamma=0.02,
            contract_multiplier=100,
            source="futu_opend",
            quote_asof=as_of,
            oi_asof=oi_asof,
            implied_volatility=0.25,
        ),
        OptionGexObservation(
            contract_symbol=f"{underlying}-P95",
            underlying_symbol=underlying,
            option_type=OptionType.PUT,
            strike=95.0,
            expiration=(as_of + timedelta(days=10)).date(),
            open_interest=800,
            gamma=0.018,
            contract_multiplier=100,
            source="futu_opend",
            quote_asof=as_of,
            oi_asof=oi_asof,
            implied_volatility=0.27,
        ),
    ]
    freshness = qualify_quote_freshness(
        rows,
        min_quote_asof=as_of - timedelta(minutes=1),
    )
    clock = qualify_options_clock_alignment(
        freshness,
        underlying_asof=as_of,
    )
    current = build_gex_evidence(
        rows,
        spot=100.0,
        market_date=as_of.date(),
        calculated_at=as_of,
        spot_asof=as_of,
        spot_source="canonical_spot",
    )
    profile = build_gamma_profile(
        rows,
        reference_spot=100.0,
        calculated_at=as_of,
    )
    current = apply_gamma_profile(current, profile)
    return build_options_intelligence_packet(
        current_gex=current,
        freshness=freshness,
        gamma_profile=profile,
        generated_at=as_of,
        clock_alignment=clock,
    )


def test_evaluator_attaches_read_only_options_context_to_us_symbol(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    packet = _qualified_options_packet(emitted)
    evaluator = CanonicalSnapshotRadarEvaluator(
        now=lambda: emitted + timedelta(seconds=5)
    )

    result = evaluator.evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
        options_packets={"AMD": packet},
    )

    assert result.status == "PASS"
    symbol = result.symbols[0]
    assert symbol.technical_state is not None
    assert symbol.options_context is not None
    assert symbol.options_context.status == "RESEARCH_ONLY"
    assert symbol.options_context.decision_permission == "BLOCKED_V0_1"
    assert symbol.options_context.trading_authority is False
    assert symbol.options_context.live_trade is False
    rendered = symbol.to_dict()["options_context"]
    assert rendered["price_acceptance_required"] is True


def test_blocked_options_context_does_not_block_price_radar_state(tmp_path):
    body = payload()
    emitted = datetime.fromisoformat(body["emitted_at_utc"])
    stale_packet = _qualified_options_packet(emitted - timedelta(hours=1))
    evaluator = CanonicalSnapshotRadarEvaluator(now=lambda: emitted)

    result = evaluator.evaluate_file(
        write_payload(tmp_path, body),
        expected_repo_sha=SHA,
        options_packets={"US.AMD": stale_packet},
    )

    assert result.status == "PASS"
    symbol = result.symbols[0]
    assert symbol.status == "RESEARCH_STATE"
    assert symbol.technical_state is not None
    assert symbol.options_context is not None
    assert symbol.options_context.status == "BLOCKED"
    assert "OPTIONS_PACKET_STALE" in symbol.options_context.warnings
    assert result.can_confirm_signal is False
