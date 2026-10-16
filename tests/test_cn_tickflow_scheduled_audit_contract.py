from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/audit-cn-tickflow-live-research.yml'


def test_market_session_cron_is_readonly_and_weekday_scoped():
    text = WORKFLOW.read_text(encoding='utf-8')
    assert "    - cron: '0,30 2-7 * * 1-5'" in text
    assert text.count('    - cron:') == 1
    slots = []
    for hour in range(2, 8):
        for minute in (0, 30):
            sh = datetime(2026, 10, 14, hour, minute,
                          tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Shanghai'))
            slots.append((sh.hour, sh.minute))
    assert slots == [
        (hour, minute) for hour in range(10, 16) for minute in (0, 30)
    ]
    assert len(slots) == 12
    assert "github.ref == 'refs/heads/main' && (" in text
    assert "github.event_name == 'schedule'" in text
    assert "github.event_name == 'workflow_dispatch'" in text


def test_scheduled_audit_preserves_research_only_boundaries():
    text = WORKFLOW.read_text(encoding='utf-8')
    assert 'Verify two isolated AWS snapshots 65 seconds apart' in text
    for required in ('source_arbiter_admission', 'radar_admission', 'live_trade', 'canonical_write'):
        assert 'assert d.get('+chr(34)+required+chr(34)+')' in text
    assert 'approve_paid_tickflow_ingestion' not in text
    assert 'cancel-in-progress: false' in text
