"""Contract tests for a single bounded, research-only US LiveFeed SSM stdout record."""
import base64
import gzip
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import textwrap

from scripts.sanitize_ssm_probe_output import project

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/aws-ssm-ops.yml"


def probe_source() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    action = text.split("            us_livefeed_status)\n", 1)[1].split(
        "            futures_opend_env_probe)\n", 1
    )[0]
    assert "journalctl" not in action
    assert "systemctl show" not in action
    assert "cat \"$status_path\"" not in action
    assert "source_tf,display_tf" in action
    return textwrap.dedent(
        action.split("          python3 - <<'PY'\n", 1)[1].split("\n          PY\n", 1)[0]
    ).replace("__RUNTIME_DIAGNOSTICS_BASE64__", base64.b64encode(
        gzip.compress((ROOT / "scripts/us_livefeed_runtime_diagnostics.py").read_bytes(), mtime=0)
    ).decode())


def execute(tmp_path: Path, *, has_snapshot: bool = True, instruments: int = 1) -> dict:
    heartbeat = {
        "controller_lifecycle": "CONNECTED",
        "delivery_mode": "REALTIME",
        "quote_right_evidence": {"query_status": "PASS", "normalized_quote_right": "LV3"},
        "account_id": "PRIVATE-ACCOUNT",
    }
    snapshot = {
        "emitted_at_utc": "2026-10-13T14:55:00+00:00",
        "bar_closure": "UNPROVEN",
        "symbols": {
            f"US.SECRET_SYMBOL_{i}": {
                "timeframes": {
                    "1m": [{"bar_end_utc": "2026-10-13T14:55:00+00:00",
                            "close": 9999.12345, "account_id": "NEVER_LOG"}],
                    "5m": [{"bar_end_utc": "2026-10-13T14:55:00+00:00"}],
                    "15m": [{"bar_end_utc": "2026-10-13T15:00:00+00:00"}],
                    "1h": [{"bar_end_utc": "2026-10-13T15:30:00+00:00"}],
                }
            }
            for i in range(instruments)
        },
    }
    heartbeat_path = tmp_path / "heartbeat.json"
    snapshot_path = tmp_path / "snapshot.json"
    heartbeat_path.write_text(json.dumps(heartbeat), encoding="utf-8")
    if has_snapshot:
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    code = probe_source()
    code = code.replace(
        "pathlib.Path('/run/stock-razor-us-livefeed/latest-heartbeat.json')",
        f"pathlib.Path({str(heartbeat_path)!r})",
    ).replace(
        "pathlib.Path('/run/stock-razor-us-livefeed/canonical-market-snapshot.json')",
        f"pathlib.Path({str(snapshot_path)!r})",
    ).replace("active=is_active()", "active=True")
    code = code.replace("runtime_namespace['collect_runtime_diagnostics']()", "{}")
    capture = StringIO()
    with redirect_stdout(capture):
        exec(compile(code, "<bounded-ssm-us-livefeed>", "exec"), {})
    lines = capture.getvalue().splitlines()
    assert len(lines) == 1
    assert len(lines[0].encode("utf-8")) < 16000
    for leaked in ("US.SECRET_SYMBOL", "9999.12345", "PRIVATE-ACCOUNT", "NEVER_LOG"):
        assert leaked not in lines[0]
    return {"raw": json.loads(lines[0]), "projected": "\n".join(project(lines[0]))}


def test_snapshot_evidence_is_bounded_and_nonadmissible(tmp_path):
    data = execute(tmp_path)
    out = data["raw"]
    assert out["status"] == "OBSERVED"
    assert out["reason"] == "RESEARCH_ONLY_NO_ADMISSION"
    assert out["query_status"] == "PASS"
    assert out["us_qot_right"] == "LV3"
    assert out["delivery_mode"] == "REALTIME"
    assert out["bar_closure"] == "UNPROVEN"
    projected = data["projected"]
    assert "symbol_count" in projected
    for tf in ('"1m"', '"5m"', '"15m"', '"1H"'):
        assert tf in projected
    assert "UNPROVEN" in projected


def test_missing_snapshot_fails_closed_and_never_prints_private_rows(tmp_path):
    data = execute(tmp_path, has_snapshot=False)
    assert data["raw"]["status"] == "BLOCKED"
    assert data["raw"]["reason"] == "RUNTIME_OR_CACHE_NOT_PROVEN"
    assert data["raw"]["symbols"] == {}


def test_safely_capped_symbol_count_never_exceeds_ssm_limit(tmp_path):
    assert execute(tmp_path, instruments=20)["raw"]["status"] == "OBSERVED"
    denied = execute(tmp_path, instruments=21)["raw"]
    assert denied["status"] == "BLOCKED"
    assert denied["reason"] == "SNAPSHOT_NO_BARS"
    assert denied["symbols"] == {}


def test_cloud_workflow_still_requires_main_readonly_without_broker_mutation():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "configure-aws-credentials@v4" in text
    assert "SANITIZED_EVIDENCE" not in probe_source()
    assert "systemctl restart" not in text.split("            us_livefeed_status)\n", 1)[1].split("            futures_opend_env_probe)\n", 1)[0]


def test_exact_runner_helper_is_embedded_within_ssm_command_limit():
    code = probe_source()
    # Include the actual shell wrapper, not just the pre-substitution source.
    assert len(("set -eu\npython3 - <<'PY'\n" + code + "\nPY\n").encode()) <= 16000
    namespace = {}
    source = (ROOT / "scripts/us_livefeed_runtime_diagnostics.py").read_bytes()
    exec(compile(source, "<runtime-diagnostics-transport>", "exec"), namespace)
    assert callable(namespace["collect_runtime_diagnostics"])
    assert "runtime_namespace['collect_runtime_diagnostics']()" in code
    text = WORKFLOW.read_text()
    action = text.split("            us_livefeed_status)\n", 1)[1].split(
        "            futures_opend_env_probe)\n", 1
    )[0]
    assert 'gzip -n -c scripts/us_livefeed_runtime_diagnostics.py | base64 -w0' in action
    assert ' -le 16000' in action
