from src.services.a_share_intraday_grid_qualification import (
    qualify_intraday_end_label_grid,
)
from src.services.a_share_intraday_semantics import (
    CN_INTRADAY_ENDPOINT_EXTENSIONS,
    TimestampSemantic,
)


END_15 = (
    "09:45", "10:00", "10:15", "10:30",
    "10:45", "11:00", "11:15", "11:30",
    "13:15", "13:30", "13:45", "14:00",
    "14:15", "14:30", "14:45", "15:00",
)
END_60 = ("10:30", "11:30", "14:00", "15:00")


def _labels(days, grid):
    return [f"{day} {clock}" for day in days for clock in grid]


def test_three_complete_15m_sessions_prove_bar_end_only():
    result = qualify_intraday_end_label_grid(
        _labels(["2026-09-28", "2026-09-29", "2026-09-30"], END_15),
        source_token="tencent",
        endpoint_id="tencent.kline_intraday",
        interval_minutes=15,
    )

    assert result.status == "PASS"
    assert result.timestamp_semantic is TimestampSemantic.BAR_END
    assert result.complete_session_dates == (
        "2026-09-28", "2026-09-29", "2026-09-30"
    )
    assert result.currentness_proven is False
    assert result.continuity_proven is False
    assert result.radar_admission == "BLOCKED"
    assert result.live_trade is False


def test_three_complete_60m_sessions_prove_bar_end_only():
    result = qualify_intraday_end_label_grid(
        _labels(["2026-09-28", "2026-09-29", "2026-09-30"], END_60),
        source_token="tencent",
        endpoint_id="tencent.kline_intraday",
        interval_minutes=60,
    )

    assert result.status == "PASS"
    assert result.timestamp_semantic is TimestampSemantic.BAR_END
    assert result.labels_examined == 12


def test_partial_latest_session_does_not_fake_currentness_or_block_history_proof():
    labels = _labels(["2026-09-25", "2026-09-28", "2026-09-29"], END_15)
    labels += [f"2026-09-30 {clock}" for clock in END_15[:4]]

    result = qualify_intraday_end_label_grid(
        labels,
        source_token="tencent",
        endpoint_id="tencent.kline_intraday",
        interval_minutes=15,
    )

    assert result.status == "PASS"
    assert result.timestamp_semantic is TimestampSemantic.BAR_END
    assert result.currentness_proven is False
    assert "2026-09-30" not in result.complete_session_dates


def test_start_label_shape_is_rejected():
    start_grid = (
        "09:30", "09:45", "10:00", "10:15",
        "10:30", "10:45", "11:00", "11:15",
        "13:00", "13:15", "13:30", "13:45",
        "14:00", "14:15", "14:30", "14:45",
    )
    result = qualify_intraday_end_label_grid(
        _labels(["2026-09-28", "2026-09-29", "2026-09-30"], start_grid),
        source_token="tencent",
        endpoint_id="tencent.kline_intraday",
        interval_minutes=15,
    )

    assert result.status == "BLOCKED"
    assert result.timestamp_semantic is TimestampSemantic.UNKNOWN
    assert any("UNEXPECTED_SESSION_LABEL" in reason for reason in result.reasons)


def test_lunch_break_label_is_rejected():
    grid = list(END_60)
    grid[2] = "12:30"
    result = qualify_intraday_end_label_grid(
        _labels(["2026-09-28", "2026-09-29", "2026-09-30"], grid),
        source_token="tencent",
        endpoint_id="tencent.kline_intraday",
        interval_minutes=60,
    )

    assert result.status == "BLOCKED"
    assert result.timestamp_semantic is TimestampSemantic.UNKNOWN


def test_duplicate_or_out_of_order_labels_fail_closed():
    labels = _labels(["2026-09-28", "2026-09-29", "2026-09-30"], END_60)
    labels.insert(2, labels[1])

    result = qualify_intraday_end_label_grid(
        labels,
        source_token="tencent",
        endpoint_id="tencent.kline_intraday",
        interval_minutes=60,
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("LABELS_NOT_STRICTLY_INCREASING",)


def test_fewer_than_three_complete_sessions_do_not_prove_semantic():
    result = qualify_intraday_end_label_grid(
        _labels(["2026-09-29", "2026-09-30"], END_15),
        source_token="tencent",
        endpoint_id="tencent.kline_intraday",
        interval_minutes=15,
    )

    assert result.status == "BLOCKED"
    assert result.timestamp_semantic is TimestampSemantic.UNKNOWN
    assert result.reasons == ("INSUFFICIENT_COMPLETE_SESSIONS",)


def test_wrong_lineage_or_endpoint_fails_closed():
    labels = _labels(["2026-09-28", "2026-09-29", "2026-09-30"], END_15)

    wrong_source = qualify_intraday_end_label_grid(
        labels,
        source_token="akshare_em",
        endpoint_id="akshare.eastmoney_intraday",
        interval_minutes=15,
    )
    wrong_endpoint = qualify_intraday_end_label_grid(
        labels,
        source_token="tencent",
        endpoint_id="akshare.tencent_spot",
        interval_minutes=15,
    )

    assert wrong_source.status == "BLOCKED"
    assert wrong_source.reasons == ("UNSUPPORTED_SOURCE_LINEAGE",)
    assert wrong_endpoint.status == "BLOCKED"
    assert wrong_endpoint.reasons == ("INVALID_INTRADAY_ENDPOINT_BINDING",)


def test_tencent_qualification_does_not_mutate_pinned_a1_capture_authority():
    assert "tencent" not in CN_INTRADAY_ENDPOINT_EXTENSIONS
    assert CN_INTRADAY_ENDPOINT_EXTENSIONS == {
        "akshare_em": frozenset({"akshare.eastmoney_intraday"})
    }
