"""Bound AWS OpenD observer to existing single owner; compile embedded runtime."""
import ast
from pathlib import Path


def test_aws_installer_embeds_readonly_candidate_preview_in_same_runtime():
    script = Path("ops/aws/install_us_opend_livefeed.sh").read_text(
        encoding="utf-8"
    )
    marker = 'cat >"$INSTALL_ROOT/run.py" <<\'PY\'\n'
    assert script.count(marker) == 1
    embedded = script.split(marker, 1)[1].split("\nPY\n", 1)[0]
    ast.parse(embedded)
    assert embedded.count("ft.OpenQuoteContext(") == 1
    assert embedded.count("bridge.start(streams)") == 1
    assert embedded.count("plan_readonly_subscriptions(") == 1
    assert '"dynamic_subscription_preview":candidate_preview' in embedded
    assert 'quota=None,now_utc=now' in embedded
    assert '"radar_admission":"BLOCKED","live_trade":False' in embedded
    assert embedded.count("ctx.subscribe(") == 0
