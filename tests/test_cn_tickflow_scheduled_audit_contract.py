from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/audit-cn-tickflow-live-research.yml'


def test_market_session_cron_is_readonly_and_weekday_scoped():
    text = WORKFLOW.read_text(encoding='utf-8')
    assert "    - cron: '20 2 * * 1-5'" in text
    assert "    - cron: '20 6 * * 1-5'" in text
    assert text.count('    - cron:') == 2
    for hour, local in ((2, 10), (6, 14)):
        sh = datetime(2026, 10, 14, hour, 20, tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Shanghai'))
        assert (sh.hour, sh.minute) == (local, 20)
    assert "if: github.ref == 'refs/heads/main'" in text


def test_scheduled_audit_preserves_research_only_boundaries():
    text = WORKFLOW.read_text(encoding='utf-8')
    assert 'Verify two isolated AWS snapshots 65 seconds apart' in text
    for required in ('source_arbiter_admission', 'radar_admission', 'live_trade', 'canonical_write'):
        assert 'assert d.get('+chr(34)+required+chr(34)+')' in text
    assert 'approve_paid_tickflow_ingestion' not in text
    assert 'cancel-in-progress: false' in text
