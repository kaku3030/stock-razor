"""CN MCP local reference conversion: unit attestation, closure and redaction."""
import json
from pathlib import Path

import pytest

from scripts.cn_mcp_offline_fixture_converter import (
    ConversionError, convert_cn_mcp_observation,
)


def sample():
    return {
        "ok": True, "status": "PASS", "symbol_status": "PASS",
        "symbol": "159611", "timeframe": "15m", "provider_used": "tencent",
        "timestamp_semantic": "BAR_END",
        "symbol_intraday_timestamp_semantics_proven": True,
        "timestamp_qualification": {"status": "PASS", "source_token": "tencent"},
        "intraday_currentness_proven": False,
        "emitted_at_utc": "2026-10-10T00:03:49+00:00",
        "api_key": "SECRET_MUST_NOT_LEAK",
        "rows": [{
            "label": "2026-10-09 15:00",
            "provider_label_raw": "202610091500",
            "open": 1.053, "high": 1.053, "low": 1.052, "close": 1.052,
            "volume_raw": 99998, "volume_unit": "HAND",
            "quality_flags": [], "provider": "tencent",
        }],
    }


def convert(d, **kwargs):
    return convert_cn_mcp_observation(
        d, symbol="159611.SZ", timeframe="15m",
        shares_per_hand=100, attested_volume_unit=True,
        attested_unadjusted=True, **kwargs,
    )


def test_explicit_attested_hand_conversion_and_private_schema():
    d = sample()
    result = convert(d)
    assert result["rows"][0]["volume"] == 9999800
    assert result["rows"][0]["bar_end_utc"] == "2026-10-09T07:00:00+00:00"
    assert result["fixture_origin"] == "REAL_CAPTURED"
    assert result["source"] == "TENCENT"
    assert result["volume_unit"] == "SHARES"
    assert "SECRET_MUST_NOT_LEAK" not in json.dumps(result)
    assert "provider_label_raw" not in json.dumps(result)


@pytest.mark.parametrize("modify,reason", [
    (lambda d: d.update(status="BLOCKED"), "UNQUALIFIED_MCP_OBSERVATION"),
    (lambda d: d.update(symbol="159363"), "SYMBOL_OR_TIMEFRAME_MISMATCH"),
    (lambda d: d.update(timestamp_semantic="BAR_START"), "TIMESTAMP_SEMANTICS_UNPROVEN"),
    (lambda d: d["timestamp_qualification"].update(source_token="eastmoney"),
     "TIMESTAMP_PROVIDER_MISMATCH"),
    (lambda d: d["rows"][0].update(volume_unit="UNKNOWN"), "UNSUPPORTED_VOLUME_UNIT"),
    (lambda d: d["rows"][0].update(quality_flags=["BAD"]), "ROW_QUALITY_UNVERIFIED"),
    (lambda d: d["rows"][0].update(close=2), "INVALID_OHLC"),
    (lambda d: d["rows"][0].update(volume_raw=-1), "INVALID_VOLUME"),
    (lambda d: d["rows"][0].update(label="2026-10-10 08:15"),
     "BAR_NOT_CLOSED_AT_CAPTURE"),
])
def test_invalid_or_unqualified_observation_blocks(modify, reason):
    d = sample()
    modify(d)
    with pytest.raises(ConversionError, match=reason):
        convert(d)


def test_explicit_attestations_required():
    d = sample()
    with pytest.raises(ConversionError, match="VOLUME_UNIT_ATTESTATION_REQUIRED"):
        convert_cn_mcp_observation(d, symbol="159611.SZ", timeframe="15m",
                                   shares_per_hand=100, attested_unadjusted=True)
    with pytest.raises(ConversionError, match="UNADJUSTED_PRICE_ATTESTATION_REQUIRED"):
        convert_cn_mcp_observation(d, symbol="159611.SZ", timeframe="15m",
                                   shares_per_hand=100, attested_volume_unit=True)
    with pytest.raises(ConversionError, match="EXPLICIT_HAND_MULTIPLIER_REQUIRED"):
        convert_cn_mcp_observation(d, symbol="159611.SZ", timeframe="15m",
                                   attested_volume_unit=True, attested_unadjusted=True)


def test_shares_input_disallows_hand_multiplier():
    d = sample()
    d["rows"][0]["volume_unit"] = "SHARES"
    with pytest.raises(ConversionError, match="UNEXPECTED_VOLUME_MULTIPLIER"):
        convert(d)
    out = convert_cn_mcp_observation(
        d, symbol="159611.SZ", timeframe="15m",
        attested_volume_unit=True, attested_unadjusted=True,
    )
    assert out["rows"][0]["volume"] == 99998


def test_no_provider_sdk_network_or_canonical_write():
    source = (Path(__file__).resolve().parents[1] /
              "scripts/cn_mcp_offline_fixture_converter.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import tickflow" not in source
    assert "import futu" not in source
    assert "os.O_EXCL" in source
    assert "0o600" in source
    assert "canonical_write" not in source
