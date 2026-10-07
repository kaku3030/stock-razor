import math

import pytest

from src.services.live_feed.futu_quote_right import (
    classify_futu_us_quote_right,
    normalize_futu_us_quote_right,
)


@pytest.mark.parametrize(
    "value",
    ["LV1", "LEVEL1", "LV2", "LEVEL2", "LV3", "LEVEL3", "QotRight.LV3"],
)
def test_fresh_supported_us_quote_right_promotes_realtime(value):
    result = classify_futu_us_quote_right(
        query_status="PASS",
        us_qot_right=value,
        age_seconds=10,
        max_age_seconds=90,
    )
    assert result.delivery_mode == "REALTIME"
    assert result.reason == "FRESH_REALTIME_US_QUOTE_RIGHT"


@pytest.mark.parametrize("value", ["BMP", "NO", "UNKNOWN", "UNKNOW", "SF", "LV4", ""])
def test_non_realtime_or_unknown_quote_right_fails_closed(value):
    result = classify_futu_us_quote_right(
        query_status="PASS",
        us_qot_right=value,
        age_seconds=10,
    )
    assert result.delivery_mode == "UNKNOWN"
    assert result.reason == "QUOTE_RIGHT_NOT_REALTIME_ENTITLEMENT"


@pytest.mark.parametrize("status", ["UNKNOWN", "BLOCKED", "FAIL", None])
def test_query_not_pass_never_promotes(status):
    result = classify_futu_us_quote_right(
        query_status=status,
        us_qot_right="LV3",
        age_seconds=1,
    )
    assert result.delivery_mode == "UNKNOWN"
    assert result.reason == "QUOTE_RIGHT_QUERY_NOT_PASS"


@pytest.mark.parametrize(
    ("age", "reason"),
    [
        (None, "QUOTE_RIGHT_AGE_INVALID"),
        (float("nan"), "QUOTE_RIGHT_AGE_INVALID"),
        (float("inf"), "QUOTE_RIGHT_AGE_INVALID"),
        (-0.1, "QUOTE_RIGHT_OBSERVED_IN_FUTURE"),
        (90.01, "QUOTE_RIGHT_EVIDENCE_STALE"),
    ],
)
def test_invalid_or_stale_evidence_never_promotes(age, reason):
    result = classify_futu_us_quote_right(
        query_status="PASS",
        us_qot_right="LV3",
        age_seconds=age,
        max_age_seconds=90,
    )
    assert result.delivery_mode == "UNKNOWN"
    assert result.reason == reason


def test_boundary_age_is_allowed():
    result = classify_futu_us_quote_right(
        query_status="PASS",
        us_qot_right="LV3",
        age_seconds=90,
        max_age_seconds=90,
    )
    assert result.delivery_mode == "REALTIME"


def test_normalizer_handles_enum_prefix_and_whitespace():
    assert normalize_futu_us_quote_right("  QotRight.Level2 ") == "LEVEL2"


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan])
def test_invalid_max_age_is_rejected(value):
    with pytest.raises(ValueError, match="max_age_seconds"):
        classify_futu_us_quote_right(
            query_status="PASS",
            us_qot_right="LV3",
            age_seconds=1,
            max_age_seconds=value,
        )
