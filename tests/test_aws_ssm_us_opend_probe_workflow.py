from pathlib import Path

WORKFLOW = Path(".github/workflows/aws-ssm-ops.yml").read_text(encoding="utf-8")


def test_us_opend_k1m_probe_is_fixed_read_only_and_fail_closed():
    assert "- us_opend_k1m_probe" in WORKFLOW
    assert 'codes=["US.AMD","US.NVDA","US.TSLA","US.AAPL","US.QQQ"]' in WORKFLOW
    assert "ft.SubType.K_1M" in WORKFLOW
    assert "subscribe_push=True" in WORKFLOW
    assert '"delivery_mode":"UNKNOWN"' in WORKFLOW
    assert '"radar_admission":"BLOCKED"' in WORKFLOW
    assert "RADAR_ADMISSION=BLOCKED" in WORKFLOW
    assert "LIVE_TRADE=NO" in WORKFLOW
    assert "OpenUSTradeContext" not in WORKFLOW
    assert "OpenSecTradeContext" not in WORKFLOW


def test_us_opend_continuity_probe_is_bounded_and_non_promoting():
    assert "- us_opend_k1m_continuity_probe" in WORKFLOW
    assert '"window_seconds":30' in WORKFLOW
    assert 'time.monotonic()-start < 30' in WORKFLOW
    assert '"delivery_mode":"UNKNOWN"' in WORKFLOW
    assert '"radar_admission":"BLOCKED"' in WORKFLOW
    assert '"nondecreasing":all(a<=b for a,b in zip(seq,seq[1:]))' in WORKFLOW
