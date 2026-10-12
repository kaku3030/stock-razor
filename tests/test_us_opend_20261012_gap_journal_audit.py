"""Deterministic US OpenD common-gap journal evidence + operator scope.

No AWS, journalctl, provider, browser, service mutation, or orders in tests.
Synthetic PID-1 log records are never emitted in the audited result.
"""
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import audit_us_opend_20261012_gap_journal as audit


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/audit-us-opend-20261012-gap-journal.yml"


def _manager(action, stamp, *, pid="1", unit=audit.UNIT, identifier="systemd", extra=None):
    micros = int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1e6)
    return json.dumps({
        "_PID": pid,
        "SYSLOG_IDENTIFIER": identifier,
        "UNIT": unit,
        "MESSAGE": extra or f"{action} US LiveFeed service.",
        "__REALTIME_TIMESTAMP": str(micros),
        "SECRET_MUST_NOT_LEAVE_PRIVATE_HOST": "redacted",
    })


def test_exact_manager_restart_overlaps_gap_but_cause_remains_unproven():
    x = audit.classify_journal_lines([
        _manager("Stopping", "2026-10-12T14:58:40Z"),
        _manager("Stopped", "2026-10-12T14:58:41Z"),
        _manager("Starting", "2026-10-12T14:58:50Z"),
        _manager("Started", "2026-10-12T14:58:51Z"),
    ])
    assert x["status"] == "RESTART_SEQUENCE_OBSERVED"
    assert x["manager_restart_pair"] == "OBSERVED"
    assert x["manager_stops_utc"] == [
        "2026-10-12T14:58:40Z", "2026-10-12T14:58:41Z",
    ]
    assert x["manager_starts_utc"] == [
        "2026-10-12T14:58:50Z", "2026-10-12T14:58:51Z",
    ]
    assert x["provider_delivery"] == "NOT_VERIFIED"
    assert x["causal_attribution"] == "NOT_VERIFIED"
    assert x["missing_provider_bar"] == "NOT_VERIFIED"
    assert x["trade_execution"] == "NO"
    assert "SECRET_MUST_NOT_LEAVE_PRIVATE_HOST" not in json.dumps(x)


def test_non_pid1_non_systemd_and_foreign_unit_never_prove_restart():
    result = audit.classify_journal_lines([
        _manager("Stopping", "2026-10-12T14:58:40Z", pid="42"),
        _manager("Started", "2026-10-12T14:58:51Z", identifier="service"),
        _manager("Started", "2026-10-12T14:58:51Z", unit="other.service"),
        _manager("Stopped", "2026-10-12T14:58:45Z",
                 extra="Stopped unrelated daemon", unit="other.service"),
    ])
    assert result["status"] == "NOT_VERIFIED"
    assert result["manager_restart_pair"] == "NOT_VERIFIED"


def test_request_phase_stopping_starting_does_not_prove_completed_restart():
    only_requested = audit.classify_journal_lines([
        _manager("Stopping", "2026-10-12T14:58:40Z"),
        _manager("Starting", "2026-10-12T14:58:41Z"),
    ])
    assert only_requested["status"] == "NOT_VERIFIED"
    assert only_requested["manager_restart_pair"] == "NOT_VERIFIED"
    assert only_requested["reason"] == "MANAGER_EVENTS_INCOMPLETE"


def test_truncated_session_or_missing_pair_never_promotes_gap_repair():
    pair = [
        _manager("Stopped", "2026-10-12T14:58:41Z"),
        _manager("Started", "2026-10-12T14:58:51Z"),
    ]
    assert audit.classify_journal_lines(pair, truncated=True)["reason"] == "BOUND_EXCEEDED"
    assert audit.classify_journal_lines(pair * 251)["reason"] == "BOUND_EXCEEDED"
    lone = audit.classify_journal_lines(pair[:1])
    assert lone["status"] == "NOT_VERIFIED"
    assert lone["reason"] == "MANAGER_EVENTS_INCOMPLETE"
    off_window = audit.classify_journal_lines([
        _manager("Stopped", "2026-10-12T14:56:41Z"),
        _manager("Started", "2026-10-12T15:03:21Z"),
    ])
    assert off_window["status"] == "NOT_VERIFIED"


def test_journal_unavailable_is_finite_not_verified_without_exception_leak(monkeypatch):
    calls = []
    def simulated_journal(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=1, stdout="", stderr="PRIVATE_SECRET")
    monkeypatch.setattr(audit.subprocess, "run", simulated_journal)
    result = audit.run_audit()
    assert result["status"] == "NOT_VERIFIED"
    assert result["reason"] == "JOURNAL_UNAVAILABLE"
    assert calls[0][0][-2:] == ["-u", audit.UNIT]
    assert calls[0][1]["capture_output"] is True
    assert "PRIVATE_SECRET" not in json.dumps(result)


def test_script_does_not_call_provider_or_modify_cloud():
    source = (ROOT / "scripts/audit_us_opend_20261012_gap_journal.py").read_text()
    assert "subprocess.run(" in source
    assert '"--output=json"' in source
    assert '"--since=2026-10-12 14:57:00 UTC"' in source
    for forbidden in ("systemctl restart", "systemctl stop", "systemctl start",
                      "request_history_kline", "get_cur_kline", "futu.OpenQuoteContext",
                      "place_order", "boto3", "SecretString", "print(completed.stdout)"):
        assert forbidden not in source


def test_aws_workflow_is_manual_main_optin_readonly_and_redacts_raw_private_journal():
    source = WORKFLOW.read_text()
    assert "workflow_dispatch:" in source
    assert "default: false" in source
    assert "github.ref == 'refs/heads/main' && inputs.approve_readonly_journal_audit == true" in source
    assert "  push:" not in source
    assert "  schedule:" not in source
    assert "persist-credentials: false" in source
    assert "Verify exact main and bounded local script before AWS OIDC" in source
    assert source.index("Verify exact main") < source.index("aws-actions/configure-aws-credentials@v4")
    assert "git ls-remote origin refs/heads/main" in source
    assert "sha256sum -c - >/dev/null" in source
    assert "AWS-RunShellScript" in source
    assert "RAW_SSM_OUTPUT_WITHHELD=YES" in source
    assert "OPEND_GAP_CAUSAL_ATTRIBUTION=NOT_VERIFIED" in source
    assert 'printf \'%s\' "$private_json" | python3 -c' in source
    assert 'echo "$private_json"' not in source
    for forbidden in ("systemctl restart", "systemctl stop", "systemctl start",
                      "request_history_kline", "get_cur_kline", "aws secretsmanager",
                      "place_order", "cancel_order", "unlock_trade"):
        assert forbidden not in source
