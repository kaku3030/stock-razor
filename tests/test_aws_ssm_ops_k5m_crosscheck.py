from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-ssm-ops.yml"


def test_k5m_crosscheck_action_is_registered_and_fail_closed():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "- us_opend_k5m_crosscheck_probe" in text
    assert "us_opend_k5m_crosscheck_probe)" in text
    assert '"probe":"us_opend_k5m_crosscheck"' in text
    assert '"purpose":"CROSS_CHECK_ONLY"' in text
    assert '"timezone_semantics":"VERIFIED_US_EASTERN"' in text
    assert '"label_semantics":"BAR_END_EMPIRICAL"' in text
    assert '"delivery_mode":"UNKNOWN"' in text
    assert '"radar_admission":"BLOCKED"' in text
    assert '"live_trade":False' in text
    assert 'print("RADAR_ADMISSION=BLOCKED")' in text
    assert 'print("LIVE_TRADE=NO")' in text


def test_k5m_crosscheck_uses_canonical_1m_aggregation_and_native_k5m():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "closed_futu_minute_to_bar" in text
    assert 'aggregate_bars(closed,"5m"' in text
    assert "compare_canonical_5m_to_futu_native" in text
    assert "ft.SubType.K_1M,ft.SubType.K_5M" in text
    assert "ctx.get_cur_kline(code,1000,ktype=ft.KLType.K_1M" in text
    assert "ctx.get_cur_kline(code,1000,ktype=ft.KLType.K_5M" in text
    assert "timezone_semantics_verified=True" in text
    assert "native_is_forming=False" in text


def test_k5m_crosscheck_only_uses_completed_prior_regular_session():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "stamp.date() >= today_et" in text
    assert "dtime(9,30) < stamp.time() <= dtime(16,0)" in text
    assert 'key=bar.bar_end.astimezone(et).strftime("%Y-%m-%d %H:%M:%S")' in text
    assert '"NO_COMPLETED_COMMON_SESSION"' in text
    assert "matched<10" in text
    assert 'status="UNKNOWN"' in text
