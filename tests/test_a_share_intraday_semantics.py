from datetime import datetime, timezone

import pytest

from src.services.a_share_intraday_semantics import (
    CN_INTRADAY_ENDPOINT_EXTENSIONS,
    CN_MARKET_TIMEZONE,
    CN_REGULAR_SESSION_SEGMENTS,
    CanonicalIntradayIdentity,
    ObservationReadiness,
    ProviderSemanticFacts,
    TimestampSemantic,
    assess_observation_readiness,
    build_cn_intraday_identity,
    observation_envelope,
)
from src.services.a_share_provider_lineage import CN_REALTIME_SOURCE_LINEAGE


def _identity(interval_minutes: int = 15):
    return build_cn_intraday_identity(
        exchange="SSE",
        instrument_id="SSE:600000",
        symbol="600000",
        interval_minutes=interval_minutes,
    )


def _facts(
    *,
    interval_minutes: int = 15,
    provider_timestamp: datetime | None = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc),
    timestamp_semantic: TimestampSemantic = TimestampSemantic.BAR_END,
    observation_complete: bool = True,
    market: str = "cn",
    symbol: str = "600000",
    observed_at: datetime = datetime(2026, 9, 10, 6, 1, tzinfo=timezone.utc),
    source_token: str = "akshare_em",
    endpoint_id: str = "akshare.eastmoney_intraday",
):
    return ProviderSemanticFacts(
        source_token=source_token,
        endpoint_id=endpoint_id,
        market=market,
        symbol=symbol,
        interval_minutes=interval_minutes,
        provider_timezone_name="Asia/Shanghai",
        provider_timestamp=provider_timestamp,
        timestamp_semantic=timestamp_semantic,
        observation_complete=observation_complete,
        provenance_ref="fixture://a-share/a1",
        observed_at=observed_at,
    )


def _now():
    return datetime(2026, 9, 10, 6, 5, tzinfo=timezone.utc)


def test_canonical_cn_session_identity_is_provider_neutral() -> None:
    identity = _identity(15)
    assert identity.market == "cn"
    assert identity.trading_calendar_id == "CN_A_SHARE"
    assert identity.timezone_name == CN_MARKET_TIMEZONE
    assert identity.session_segments == CN_REGULAR_SESSION_SEGMENTS
    assert identity.session_segments == (("09:30", "11:30"), ("13:00", "15:00"))
    assert "provider" not in identity.to_dict()


@pytest.mark.parametrize("interval_minutes", [15, 60])
def test_a1_explicitly_supports_k15_and_k60_identity(interval_minutes: int) -> None:
    identity = _identity(interval_minutes)
    assert identity.interval_minutes == interval_minutes


def test_unknown_source_identity_fails_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(source_token="unknown_provider"),
        now=_now(),
    )
    assert readiness is ObservationReadiness.UNKNOWN_SOURCE_IDENTITY


def test_registered_source_with_wrong_intraday_endpoint_fails_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(endpoint_id="akshare.sina_spot"),
        now=_now(),
    )
    assert readiness is ObservationReadiness.INVALID_INTRADAY_ENDPOINT_BINDING


def test_registered_source_with_governed_intraday_extension_may_reach_ready() -> None:
    readiness = assess_observation_readiness(_identity(), _facts(), now=_now())
    assert readiness is ObservationReadiness.READY_FOR_DERIVED_GATES
    assert "akshare_em" in CN_REALTIME_SOURCE_LINEAGE
    assert CN_INTRADAY_ENDPOINT_EXTENSIONS["akshare_em"] == frozenset(
        {"akshare.eastmoney_intraday"}
    )
    assert CN_REALTIME_SOURCE_LINEAGE["akshare_em"].endpoint_id == "akshare.eastmoney_spot"


def test_unknown_timestamp_semantics_fail_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(timestamp_semantic=TimestampSemantic.UNKNOWN),
        now=_now(),
    )
    assert readiness is ObservationReadiness.UNKNOWN_TIMESTAMP_SEMANTIC


def test_missing_provider_timestamp_fails_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(provider_timestamp=None),
        now=_now(),
    )
    assert readiness is ObservationReadiness.MISSING_PROVIDER_TIMESTAMP


def test_timezone_naive_provider_timestamp_fails_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(provider_timestamp=datetime(2026, 9, 10, 14, 0)),
        now=_now(),
    )
    assert readiness is ObservationReadiness.NAIVE_PROVIDER_TIMESTAMP


def test_future_provider_timestamp_fails_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(
            provider_timestamp=datetime(2026, 9, 10, 6, 6, tzinfo=timezone.utc),
            observed_at=datetime(2026, 9, 10, 6, 6, tzinfo=timezone.utc),
        ),
        now=_now(),
    )
    assert readiness is ObservationReadiness.FUTURE_OBSERVATION_TIME


def test_future_observation_time_fails_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(observed_at=datetime(2026, 9, 10, 6, 6, tzinfo=timezone.utc)),
        now=_now(),
    )
    assert readiness is ObservationReadiness.FUTURE_OBSERVATION_TIME


def test_provider_timestamp_after_observation_fails_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(
            provider_timestamp=datetime(2026, 9, 10, 6, 2, tzinfo=timezone.utc),
            observed_at=datetime(2026, 9, 10, 6, 1, tzinfo=timezone.utc),
        ),
        now=_now(),
    )
    assert readiness is ObservationReadiness.PROVIDER_TIMESTAMP_AFTER_OBSERVED_AT


def test_incomplete_provider_observation_fails_closed() -> None:
    readiness = assess_observation_readiness(
        _identity(),
        _facts(observation_complete=False),
        now=_now(),
    )
    assert readiness is ObservationReadiness.PROVIDER_OBSERVATION_INCOMPLETE


@pytest.mark.parametrize(
    "facts",
    [
        _facts(market="us"),
        _facts(symbol="000001"),
        _facts(interval_minutes=60),
    ],
)
def test_identity_mismatch_fails_closed(facts: ProviderSemanticFacts) -> None:
    readiness = assess_observation_readiness(_identity(15), facts, now=_now())
    assert readiness is ObservationReadiness.IDENTITY_MISMATCH


def test_same_trading_date_old_bar_is_not_promoted_to_currentness() -> None:
    old_same_day = _facts(
        provider_timestamp=datetime(2026, 9, 10, 1, 45, tzinfo=timezone.utc),
        timestamp_semantic=TimestampSemantic.BAR_END,
    )
    envelope = observation_envelope(_identity(), old_same_day, now=_now())

    assert envelope["readiness"] == ObservationReadiness.READY_FOR_DERIVED_GATES.value
    assert envelope["governance"]["same_trading_date_proves_currentness"] is False
    assert envelope["governance"]["positive_currentness_authorized"] is False


def test_delayed_but_valid_provider_timestamp_remains_fact_not_freshness_decision() -> None:
    delayed = _facts(
        provider_timestamp=datetime(2026, 9, 10, 5, 30, tzinfo=timezone.utc),
        timestamp_semantic=TimestampSemantic.BAR_END,
    )
    envelope = observation_envelope(_identity(), delayed, now=_now())
    assert envelope["readiness"] == ObservationReadiness.READY_FOR_DERIVED_GATES.value
    assert envelope["governance"]["positive_currentness_authorized"] is False


def test_provider_alias_is_not_part_of_canonical_identity() -> None:
    envelope = observation_envelope(_identity(), _facts(), now=_now())
    assert envelope["identity"]["instrument_id"] == "SSE:600000"
    assert envelope["provider_facts"]["source_token"] == "akshare_em"
    assert "source_token" not in envelope["identity"]
    assert "endpoint_id" not in envelope["identity"]


def test_observation_envelope_preserves_provenance_and_market_local_timestamp() -> None:
    envelope = observation_envelope(_identity(), _facts(), now=_now())
    assert envelope["provider_facts"]["provenance_ref"] == "fixture://a-share/a1"
    assert envelope["provider_timestamp_market_local"].startswith("2026-09-10T14:00:00+08:00")


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        assess_observation_readiness(_identity(), _facts(), now=datetime(2026, 9, 10, 14, 5))


def test_noncanonical_session_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="session_segments"):
        CanonicalIntradayIdentity(
            market="cn",
            exchange="SSE",
            instrument_id="SSE:600000",
            symbol="600000",
            trading_calendar_id="CN_A_SHARE",
            timezone_name="Asia/Shanghai",
            session_segments=(("09:30", "15:00"),),
            interval_minutes=15,
            adjustment_mode="NONE",
        )


def test_noncanonical_trading_calendar_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="trading calendar"):
        CanonicalIntradayIdentity(
            market="cn",
            exchange="SSE",
            instrument_id="SSE:600000",
            symbol="600000",
            trading_calendar_id="ARBITRARY_CALENDAR",
            timezone_name="Asia/Shanghai",
            session_segments=CN_REGULAR_SESSION_SEGMENTS,
            interval_minutes=15,
            adjustment_mode="NONE",
        )
