import json

from scripts.sanitize_ssm_probe_output import project


def test_projection_keeps_bar_freshness_but_drops_raw_market_payload() -> None:
    raw = json.dumps({
        "probe": "us_livefeed_status",
        "schema": "safe-v1",
        "emitted_at_utc": "2026-10-13T13:00:00Z",
        "symbols": {
            "US.AMD": {"timeframes": {
                "5m": {"count": 12, "latest_end_utc": "2026-10-13T12:55:00Z"},
            }},
        },
        "close": 123.45,
        "volume": 999,
        "runtime_instance_id": "private-instance",
    })
    result = "\n".join(project(raw))
    assert "SANITIZED_PROBE" in result
    assert "symbol_count" in result
    assert "latest_end_utc" in result
    assert "123.45" not in result
    assert "999" not in result
    assert "private-instance" not in result


def test_projection_keeps_fixed_status_lines_only() -> None:
    result = "\n".join(project(
        "SUBSCRIPTION=PASS\nUS_QOT_RIGHT=UNKNOWN\nSUBSCRIPTION=secret-token\nACCOUNT_ID=private\n"
    ))
    assert "SUBSCRIPTION=PASS" in result
    assert "US_QOT_RIGHT=UNKNOWN" in result
    assert "secret-token" not in result
    assert "ACCOUNT_ID" not in result
