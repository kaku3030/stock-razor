from __future__ import annotations

import math
from dataclasses import dataclass


REALTIME_US_QUOTE_RIGHTS = frozenset(
    {"LV1", "LEVEL1", "LV2", "LEVEL2", "LV3", "LEVEL3"}
)


def normalize_futu_us_quote_right(value: object) -> str:
    normalized = str(value or "UNKNOWN").strip().upper()
    for prefix in ("QOTRIGHT.", "QOT_RIGHT."):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized or "UNKNOWN"


@dataclass(frozen=True)
class FutuUsQuoteRightClassification:
    query_status: str
    raw_quote_right: str
    normalized_quote_right: str
    age_seconds: float | None
    max_age_seconds: float
    delivery_mode: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "query_status": self.query_status,
            "raw_quote_right": self.raw_quote_right,
            "normalized_quote_right": self.normalized_quote_right,
            "age_seconds": self.age_seconds,
            "max_age_seconds": self.max_age_seconds,
            "delivery_mode": self.delivery_mode,
            "reason": self.reason,
        }


def classify_futu_us_quote_right(
    *,
    query_status: object,
    us_qot_right: object,
    age_seconds: float | int | None,
    max_age_seconds: float = 90.0,
) -> FutuUsQuoteRightClassification:
    if max_age_seconds <= 0 or not math.isfinite(float(max_age_seconds)):
        raise ValueError("max_age_seconds must be positive and finite")

    status = str(query_status or "UNKNOWN").strip().upper() or "UNKNOWN"
    raw = str(us_qot_right or "UNKNOWN").strip() or "UNKNOWN"
    normalized = normalize_futu_us_quote_right(raw)

    parsed_age: float | None
    if age_seconds is None:
        parsed_age = None
    else:
        try:
            parsed_age = float(age_seconds)
        except (TypeError, ValueError):
            parsed_age = None

    if status != "PASS":
        return FutuUsQuoteRightClassification(
            status,
            raw,
            normalized,
            parsed_age,
            float(max_age_seconds),
            "UNKNOWN",
            "QUOTE_RIGHT_QUERY_NOT_PASS",
        )
    if parsed_age is None or not math.isfinite(parsed_age):
        return FutuUsQuoteRightClassification(
            status,
            raw,
            normalized,
            parsed_age,
            float(max_age_seconds),
            "UNKNOWN",
            "QUOTE_RIGHT_AGE_INVALID",
        )
    if parsed_age < 0:
        return FutuUsQuoteRightClassification(
            status,
            raw,
            normalized,
            parsed_age,
            float(max_age_seconds),
            "UNKNOWN",
            "QUOTE_RIGHT_OBSERVED_IN_FUTURE",
        )
    if parsed_age > max_age_seconds:
        return FutuUsQuoteRightClassification(
            status,
            raw,
            normalized,
            parsed_age,
            float(max_age_seconds),
            "UNKNOWN",
            "QUOTE_RIGHT_EVIDENCE_STALE",
        )
    if normalized not in REALTIME_US_QUOTE_RIGHTS:
        return FutuUsQuoteRightClassification(
            status,
            raw,
            normalized,
            parsed_age,
            float(max_age_seconds),
            "UNKNOWN",
            "QUOTE_RIGHT_NOT_REALTIME_ENTITLEMENT",
        )
    return FutuUsQuoteRightClassification(
        status,
        raw,
        normalized,
        parsed_age,
        float(max_age_seconds),
        "REALTIME",
        "FRESH_REALTIME_US_QUOTE_RIGHT",
    )
