import json
from datetime import date, datetime, timedelta, timezone

from src.services.options_intelligence import (
    OptionGexObservation,
    apply_gamma_profile,
    build_gamma_profile,
    build_gex_evidence,
    build_options_intelligence_packet,
    qualify_options_clock_alignment,
    qualify_quote_freshness,
)
from src.services.options_intelligence.gex import OptionType
from src.services.options_intelligence.runtime_snapshot import (
    SCHEMA,
    build_options_intelligence_runtime_snapshot,
    write_options_intelligence_runtime_snapshot,
)
from src.services.stock_radar_v2.options_context_reader import (
    RadarOptionsContextReader,
    load_options_context_snapshot_payload,
)


NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
SHA = "b" * 40


def _packet():
    expiry = date(2026, 10, 16)
    quote_asof = NOW - timedelta(minutes=2)
    oi_asof = NOW - timedelta(hours=1)
    rows = [
        OptionGexObservation(
            contract_symbol="US.QQQ261016C760000",
            underlying_symbol="QQQ",
            option_type=OptionType.CALL,
            strike=760,
            expiration=expiry,
            open_interest=1000,
            gamma=0.02,
            contract_multiplier=100,
            source="futu_opend",
            quote_asof=quote_asof,
            oi_asof=oi_asof,
            implied_volatility=0.24,
        ),
        OptionGexObservation(
            contract_symbol="US.QQQ261016P750000",
            underlying_symbol="QQQ",
            option_type=OptionType.PUT,
            strike=750,
            expiration=expiry,
            open_interest=800,
            gamma=0.018,
            contract_multiplier=100,
            source="futu_opend",
            quote_asof=quote_asof,
            oi_asof=oi_asof,
            implied_volatility=0.25,
        ),
    ]
    freshness = qualify_quote_freshness(
        rows,
        min_quote_asof=NOW - timedelta(minutes=15),
    )
    clock = qualify_options_clock_alignment(
        freshness,
        underlying_asof=NOW - timedelta(minutes=1),
    )
    current = build_gex_evidence(
        rows,
        spot=756.2,
        market_date=date(2026, 10, 7),
        calculated_at=NOW,
        spot_asof=NOW - timedelta(minutes=1),
        spot_source="regular_last",
    )
    profile = build_gamma_profile(
        rows,
        reference_spot=756.2,
        calculated_at=NOW,
    )
    current = apply_gamma_profile(current, profile)
    return build_options_intelligence_packet(
        current_gex=current,
        freshness=freshness,
        gamma_profile=profile,
        generated_at=NOW,
        clock_alignment=clock,
    )


def _snapshot():
    return build_options_intelligence_runtime_snapshot(
        {"US.QQQ": _packet()},
        runtime_instance_id="options-runtime-1",
        repo_sha=SHA,
        sequence=7,
        emitted_at_utc=NOW,
    )


def test_runtime_snapshot_round_trip_is_context_only(tmp_path):
    payload = _snapshot()

    assert payload["schema"] == SCHEMA
    assert payload["research_only"] is True
    assert payload["trading_authority"] is False
    assert payload["live_trade"] is False
    assert set(payload["symbols"]) == {"US.QQQ"}

    path = tmp_path / "options-intelligence.json"
    write_options_intelligence_runtime_snapshot(path, payload)
    result = RadarOptionsContextReader(now=lambda: NOW + timedelta(seconds=5)).read_file(
        path,
        expected_repo_sha=SHA,
    )

    assert result.status == "PASS"
    assert result.research_only is True
    assert result.trading_authority is False
    assert result.live_trade is False
    context = result.by_symbol()["US.QQQ"]
    assert context.symbol == "US.QQQ"
    assert context.radar_admission == "CONTEXT_ONLY"
    assert context.decision_permission == "BLOCKED_V0_1"
    assert context.trading_authority is False
    assert context.live_trade is False
    assert context.clock_status == "PASS_RESEARCH"
    assert context.call_wall == 760
    assert context.put_wall == 750


def test_runtime_snapshot_writer_uses_atomic_replace(tmp_path):
    destination = tmp_path / "nested" / "options.json"
    write_options_intelligence_runtime_snapshot(destination, _snapshot())

    assert destination.exists()
    assert not destination.with_name(destination.name + ".tmp").exists()
    parsed = json.loads(destination.read_text(encoding="utf-8"))
    assert parsed["sequence"] == 7


def test_reader_fails_closed_on_trading_authority_escalation(tmp_path):
    payload = _snapshot()
    payload["symbols"]["US.QQQ"]["trading_authority"] = True
    path = tmp_path / "options.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = RadarOptionsContextReader(now=lambda: NOW).read_file(path)

    assert result.status == "BLOCKED"
    assert result.contexts == ()
    assert result.reasons[0].startswith("SOURCE_INVALID:")


def test_reader_fails_closed_on_decision_permission_escalation(tmp_path):
    payload = _snapshot()
    payload["symbols"]["US.QQQ"]["decision_permission"] = "ENTER"
    path = tmp_path / "options.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = RadarOptionsContextReader(now=lambda: NOW).read_file(path)

    assert result.status == "BLOCKED"
    assert result.contexts == ()


def test_reader_rejects_repo_mismatch_stale_and_future_exports(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    mismatch = RadarOptionsContextReader(now=lambda: NOW).read_file(
        path,
        expected_repo_sha="c" * 40,
    )
    assert mismatch.status == "BLOCKED"
    assert mismatch.reasons == ("SOURCE_REPO_SHA_MISMATCH",)

    stale = RadarOptionsContextReader(
        max_age_seconds=60,
        now=lambda: NOW + timedelta(minutes=2),
    ).read_file(path, expected_repo_sha=SHA)
    assert stale.status == "BLOCKED"
    assert stale.reasons == ("SOURCE_EXPORT_STALE",)

    future = RadarOptionsContextReader(
        max_future_skew_seconds=5,
        now=lambda: NOW - timedelta(seconds=10),
    ).read_file(path, expected_repo_sha=SHA)
    assert future.status == "BLOCKED"
    assert future.reasons == ("SOURCE_EXPORT_FROM_FUTURE",)


def test_loader_requires_clock_alignment_and_canonical_symbol():
    missing_clock = _snapshot()
    missing_clock["symbols"]["US.QQQ"]["clock_alignment"] = None
    try:
        load_options_context_snapshot_payload(missing_clock)
    except ValueError as exc:
        assert "clock_alignment" in str(exc)
    else:
        raise AssertionError("missing clock alignment should fail closed")

    bad_symbol = _snapshot()
    bad_symbol["symbols"] = {"QQQ": bad_symbol["symbols"]["US.QQQ"]}
    try:
        load_options_context_snapshot_payload(bad_symbol)
    except ValueError as exc:
        assert "canonical US symbols" in str(exc)
    else:
        raise AssertionError("non-canonical snapshot symbol should fail closed")


def test_runtime_snapshot_rejects_empty_packet_set():
    try:
        build_options_intelligence_runtime_snapshot(
            {},
            runtime_instance_id="options-runtime-1",
            repo_sha=SHA,
            sequence=1,
            emitted_at_utc=NOW,
        )
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("empty options snapshot should fail closed")


def test_reader_blocks_invalid_expected_source_sha_without_crashing(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    result = RadarOptionsContextReader(now=lambda: NOW).read_file(
        path,
        expected_repo_sha="not-a-sha",
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("EXPECTED_SOURCE_REPO_SHA_INVALID",)
