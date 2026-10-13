from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts.audit_cloud_runtime_readonly import (
    _COMPONENTS,
    audit_twice,
    mcp_install_evidence,
    component_snapshot,
)

NOW = datetime(2026, 10, 8, 6, 30, tzinfo=timezone.utc)


def payload_for(name, *, seq=5, emitted=None, **changes):
    _, _, kind_field, kind_value = _COMPONENTS[name]
    payload = {
        kind_field: kind_value,
        "emitted_at_utc": (emitted or NOW - timedelta(seconds=2)).isoformat(),
        "sequence": seq,
        "repo_sha": "a" * 40,
        "worker_repo_sha": "b" * 40,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "status": "PASS",
        "poll_status": "PASS",
        "radar_analysis_performed": True,
        "radar_analysis_latency_ms": 28.5,
        "data_to_radar_latency_ms": 140.0,
        "failure_reason": "SECRET_NEVER_PRINT",
        "api_key": "SECRET_NEVER_PRINT",
    }
    payload.update(changes)
    return payload


def probe(name, payload, active=True):
    return component_snapshot(
        name,
        now=NOW,
        check_unit=lambda unit: active,
        read_json=lambda path: payload,
    )


@pytest.mark.parametrize("name", sorted(_COMPONENTS))
def test_current_research_component_is_operational_only(name):
    result = probe(name, payload_for(name))
    assert result["operational_state"] == "HEARTBEAT_CURRENT"
    assert result["heartbeat_age_seconds"] == 2
    assert result["sequence"] == 5
    assert result["safety_evidence"] == "COMPLETE"
    assert "SECRET_NEVER_PRINT" not in json.dumps(result)
    if name.endswith("_radar"):
        assert result["radar_analysis_latency_ms"] == 28.5
    else:
        assert result["radar_analysis_latency_ms"] is None


def test_legacy_us_livefeed_missing_research_keys_is_explicit_unknown():
    source = payload_for("us_livefeed")
    source.pop("research_only")
    source.pop("can_confirm_signal")
    result = probe("us_livefeed", source)
    assert result["operational_state"] == "HEARTBEAT_CURRENT"
    assert result["safety_evidence"] == "INCOMPLETE"
    assert result["research_only"] is None


@pytest.mark.parametrize("bad", [
    {"live_trade": True},
    {"radar_admission": "ADMITTED"},
    {"can_confirm_signal": True},
    {"research_only": False},
])
def test_any_unsafe_governance_fails_closed(bad):
    result = probe("cn_observer", payload_for("cn_observer", **bad))
    assert result["operational_state"] == "SAFETY_CONTRACT_INVALID"
    assert result["safety_evidence"] == "INVALID"


def test_missing_or_malformed_json_does_not_manufacture_heartbeat():
    result = probe("cn_radar", None)
    assert result["operational_state"] == "HEARTBEAT_UNAVAILABLE"
    assert result["sequence"] is None


def test_schema_mismatch_blocks_heartbeat():
    result = probe("us_radar", payload_for("us_radar", type="wrong"))
    assert result["operational_state"] == "SCHEMA_MISMATCH"


def test_stale_and_inactive_are_separately_reported():
    stale = probe(
        "cn_observer",
        payload_for("cn_observer", emitted=NOW - timedelta(minutes=7)),
    )
    inactive = probe("cn_observer", payload_for("cn_observer"), active=False)
    assert stale["operational_state"] == "HEARTBEAT_STALE"
    assert inactive["operational_state"] == "UNIT_INACTIVE"


def test_future_source_timestamp_is_not_fake_zero_latency():
    result = probe(
        "us_livefeed",
        payload_for("us_livefeed", emitted=NOW + timedelta(seconds=2)),
    )
    assert result["operational_state"] == "CLOCK_REVERSAL"
    assert result["heartbeat_age_seconds"] is None


def test_missing_or_boolean_sequence_stays_unknown():
    result = probe("cn_radar", payload_for("cn_radar", sequence=True))
    assert result["operational_state"] == "SEQUENCE_UNKNOWN"


def test_two_samples_show_progress_without_off_pc_promotion():
    seen = {name: 0 for name in _COMPONENTS}

    def read(path):
        name = next(k for k, v in _COMPONENTS.items() if v[1] == path)
        seen[name] += 1
        return payload_for(name, seq=seen[name])

    result = audit_twice(
        interval_seconds=0,
        check_unit=lambda unit: True,
        read_json=read,
        clock=lambda: NOW,
        sleeper=lambda _: pytest.fail("should not sleep"),
    )
    assert result["audit_status"] == "COMPLETE"
    assert result["all_components_current"] is True
    assert result["all_safety_evidence_complete"] is True
    assert all(result["heartbeat_progress_observed"].values())
    assert result["off_pc_independent_acquisition"] == "NOT_VERIFIED"
    assert result["intraday_data_quality"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] == "NO"
    assert result["can_confirm_signal"] is False
    assert result["external_notifications_sent"] == 0
    assert "SECRET_NEVER_PRINT" not in json.dumps(result)


def test_empty_runtime_evidence_is_reported_as_gaps():
    result = audit_twice(
        interval_seconds=0,
        read_json=lambda path: None,
        check_unit=lambda unit: False,
        clock=lambda: NOW,
    )
    assert result["audit_status"] == "COMPLETE_WITH_GAPS"
    assert result["all_components_current"] is False
    assert not any(result["heartbeat_progress_observed"].values())


def test_interval_out_of_bounds_rejected():
    with pytest.raises(ValueError):
        audit_twice(interval_seconds=-1)
    with pytest.raises(ValueError):
        audit_twice(interval_seconds=61)



def test_midread_heartbeat_publish_is_not_a_fake_clock_reversal():
    """A 4-Hz Radar JSON replacement can occur AFTER the audit's pre-read time."""
    before = NOW
    emitted = NOW + timedelta(milliseconds=90)
    postread = NOW + timedelta(milliseconds=145)
    snapshot = payload_for("us_radar", emitted=emitted)
    old_order = component_snapshot(
        "us_radar", now=before, check_unit=lambda _: True,
        read_json=lambda _: snapshot,
    )
    assert old_order["operational_state"] == "CLOCK_REVERSAL"
    observed = component_snapshot(
        "us_radar", now=before, check_unit=lambda _: True,
        read_json=lambda _: snapshot, clock_after_read=lambda: postread,
    )
    assert observed["operational_state"] == "HEARTBEAT_CURRENT"
    assert observed["heartbeat_age_seconds"] == pytest.approx(0.055)
    assert observed["sequence"] == 5
    assert "SECRET_NEVER_PRINT" not in json.dumps(observed)


def test_postread_clock_does_not_hide_real_clock_or_future_timestamp():
    later_than_read = payload_for("us_radar", emitted=NOW + timedelta(seconds=4))
    future = component_snapshot(
        "us_radar", now=NOW, check_unit=lambda _: True,
        read_json=lambda _: later_than_read,
        clock_after_read=lambda: NOW + timedelta(milliseconds=100),
    )
    assert future["operational_state"] == "CLOCK_REVERSAL"
    assert future["heartbeat_age_seconds"] is None

    normal = payload_for("us_radar", emitted=NOW - timedelta(seconds=1))
    backwards = component_snapshot(
        "us_radar", now=NOW, check_unit=lambda _: True,
        read_json=lambda _: normal,
        clock_after_read=lambda: NOW - timedelta(milliseconds=10),
    )
    assert backwards["operational_state"] == "CLOCK_REVERSAL"
    invalid = component_snapshot(
        "us_radar", now=NOW, check_unit=lambda _: True,
        read_json=lambda _: normal, clock_after_read=lambda: NOW.replace(tzinfo=None),
    )
    assert invalid["operational_state"] == "TIMESTAMP_INVALID"


def test_two_sample_audit_uses_postread_clock_per_component():
    """Exercise the real clock/load ordering without AWS or a 4-Hz subprocess."""
    current = [NOW]
    seen = {name: 0 for name in _COMPONENTS}
    names_by_path = {entry[1]: name for name, entry in _COMPONENTS.items()}

    def clock():
        reading = current[0]
        current[0] += timedelta(milliseconds=20)
        return reading

    def read_json(path):
        name = names_by_path[path]
        seen[name] += 1
        # JSON is atomically updated while the audit reads it, after the
        # earlier clock but before the post-file-read clock.
        emitted = current[0] + timedelta(milliseconds=3)
        current[0] += timedelta(milliseconds=8)
        return payload_for(name, seq=seen[name], emitted=emitted)

    result = audit_twice(
        interval_seconds=0, clock=clock,
        check_unit=lambda _: True, read_json=read_json,
        sleeper=lambda _: pytest.fail("should not sleep"),
    )
    assert result["audit_status"] == "COMPLETE"
    assert result["all_components_current"] is True
    assert all(result["heartbeat_progress_observed"].values())
    assert all(x["operational_state"] == "HEARTBEAT_CURRENT"
               for x in result["aws_components"].values())
    assert result["off_pc_independent_acquisition"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] == "NO"


def test_mcp_installation_inventory_is_source_only_and_secret_free():
    source = """from mcp.server.fastmcp import FastMCP
mcp = FastMCP("test")
@mcp.tool()
def get_cloud_ops_status() -> dict:
    return {"private": "NEVER_EXPOSE_RAW"}"""
    report = mcp_install_evidence(
        active=lambda unit: unit == "stock-razor-mcp.service",
        source=lambda: source,
        revision=lambda: "a" * 40,
    )
    assert report["status"] == "SOURCE_PRESENT_PROTOCOL_NOT_VERIFIED"
    assert report["deployed_repo_sha"] == "a" * 40
    assert report["cloud_ops_tool_in_deployed_source"] is True
    assert report["authenticated_protocol_verified"] is False
    assert "NEVER_EXPOSE_RAW" not in json.dumps(report)


@pytest.mark.parametrize("text,expected", [
    ("def get_cloud_ops_status(): pass", False),
    ("# @mcp.tool()\ndef get_cloud_ops_status(): pass", False),
    ("@other.tool()\ndef get_cloud_ops_status(): pass", False),
    ("@mcp.tool()\ndef get_cloud_ops_status(): pass", True),
    ("not python code!?!", False),
])
def test_mcp_installation_never_inferrs_tool_from_name_alone(text, expected):
    report = mcp_install_evidence(
        active=lambda _: True,
        source=lambda: text,
        revision=lambda: "a" * 40,
    )
    assert report["cloud_ops_tool_in_deployed_source"] is expected
    assert report["authenticated_protocol_verified"] is False
    if not expected:
        assert report["status"] == "BLOCKED"


def test_mcp_installation_fail_closed_if_file_or_sha_missing():
    def error():
        raise OSError("PRIVATE_HOST_DETAIL")
    result = mcp_install_evidence(
        active=lambda _: True, source=error, revision=error,
    )
    assert result["status"] == "BLOCKED"
    assert result["deployed_repo_sha"] is None
    assert result["cloud_ops_tool_in_deployed_source"] is False
    assert "PRIVATE_HOST_DETAIL" not in json.dumps(result)
    assert mcp_install_evidence(
        active=lambda _: False, source=lambda: "@mcp.tool()\ndef get_cloud_ops_status(): pass",
        revision=lambda: "a" * 40,
    )["status"] == "BLOCKED"


def test_cloud_audit_reports_mcp_provenance_without_qualifying_market():
    fixture = {
        "mcp_unit_active": True, "deployed_repo_sha": "a" * 40,
        "cloud_ops_tool_in_deployed_source": True,
        "authenticated_protocol_verified": False,
        "status": "SOURCE_PRESENT_PROTOCOL_NOT_VERIFIED",
    }
    seen = {name: 0 for name in _COMPONENTS}
    def read(path):
        name = next(name for name, parts in _COMPONENTS.items() if parts[1] == path)
        seen[name] += 1
        return payload_for(name, seq=seen[name])
    result = audit_twice(
        interval_seconds=0, clock=lambda: NOW,
        read_json=read, check_unit=lambda _: True,
        read_mcp=lambda: fixture,
    )
    assert result["audit_status"] == "COMPLETE"
    assert result["mcp_deployment_evidence"] == fixture
    assert result["off_pc_independent_acquisition"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] == "NO"


def test_ssm_workflow_is_read_only_and_uses_pinned_main():
    source = Path(".github/workflows/audit-cloud-independent-runtime.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in source
    assert "aws-actions/configure-aws-credentials@v4" in source
    assert "ssm send-command" in source
    assert "AWS-RunShellScript" in source
    assert 'script_sha="$(git rev-parse HEAD)"' in source
    assert "scripts/audit_cloud_runtime_readonly.py" in source
    assert "RADAR_ADMISSION=BLOCKED" in source
    assert "LIVE_TRADE=NO" in source
    assert "systemctl restart" not in source
    assert "systemctl stop" not in source
    assert "pip install" not in source


def test_ssm_cloud_runtime_audit_is_private_repo_compatible_and_sha_pinned():
    """Deliver the existing read-only probe from immutable CI checkout.

    A workflow that curls public raw GitHub will fail the moment the repo
    changes to PRIVATE, even if the local source bundle verifier succeeds.
    """
    import base64

    workflow = Path(".github/workflows/audit-cloud-independent-runtime.yml").read_text(
        encoding="utf-8"
    )
    source_bytes = Path("scripts/audit_cloud_runtime_readonly.py").read_bytes()
    assert "workflow_dispatch:" in workflow
    assert 'ref: ${{ github.sha }}' in workflow
    assert 'test "$script_sha" = "${{ github.sha }}"' in workflow
    assert 'source_b64="$(base64 -w0 < scripts/audit_cloud_runtime_readonly.py)"' in workflow
    assert "source_hash=" in workflow
    assert "sha256sum -c - >/dev/null" in workflow
    assert "PRIVATE_SAFE_AUDIT_SSM_PAYLOAD_TOO_LARGE" in workflow
    assert "          set -eu\n          umask 077" in workflow
    assert "remote <<REMOTE || true" in workflow
    assert "https://raw.githubusercontent.com/" not in workflow
    assert "curl -fsSL" not in workflow
    assert "git clone" not in workflow
    assert "systemctl restart" not in workflow
    assert "systemctl stop" not in workflow
    assert "LIVE_TRADE=NO" in workflow
    assert "RADAR_ADMISSION=BLOCKED" in workflow
    # An extra margin covers the remote shell wrapper and JSON escaping.
    assert len(base64.b64encode(source_bytes)) + 1600 < 18000


def test_private_source_dependency_scan_excludes_migrated_ssm_cloud_audit():
    from scripts.audit_private_repo_deploy_dependencies import scan_private_repo_blockers

    repo_root = Path(__file__).resolve().parents[1]
    hits = scan_private_repo_blockers(repo_root)
    assert all(
        hit.file != ".github/workflows/audit-cloud-independent-runtime.yml"
        for hit in hits
    )


def test_ssm_inline_source_transport_executes_under_posix_sh():
    """Exercise the actual remote template with harmless synthetic Python.

    This catches dash/sh syntax, bash-only pipefail and checksum transport
    regressions without connecting to AWS or executing a provider client.
    """
    import base64
    from hashlib import sha256
    import shutil
    import subprocess

    if not shutil.which("sh"):
        pytest.skip("requires a POSIX shell")
    source = Path(".github/workflows/audit-cloud-independent-runtime.yml").read_text(
        encoding="utf-8"
    )
    marker = "read -r -d '' remote <<REMOTE || true\n"
    embedded = source.split(marker, 1)[1].split("\n          REMOTE", 1)[0]
    embedded = "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in embedded.splitlines()
    )
    # A real runner expands these two values when constructing the here-doc.
    # Our local test performs the same substitution without any credentials.
    fixture = b'print("SSM_PRIVATE_TRANSPORT_ROUNDTRIP=PASS")\n'
    source_b64 = base64.b64encode(fixture).decode("ascii")
    source_digest = sha256(fixture).hexdigest()
    remote = embedded.replace("$source_b64", source_b64)
    remote = remote.replace("$source_hash", source_digest)
    remote = remote.replace("\\$", "$")
    good = subprocess.run(
        ["sh", "-c", remote], capture_output=True, text=True, timeout=10
    )
    assert good.returncode == 0, good.stderr
    assert "SSM_PRIVATE_TRANSPORT_ROUNDTRIP=PASS" in good.stdout
    failed = subprocess.run(
        ["sh", "-c", remote.replace(source_digest, "0" * 64)],
        capture_output=True, text=True, timeout=10,
    )
    assert failed.returncode != 0
    assert "SSM_PRIVATE_TRANSPORT_ROUNDTRIP=PASS" not in failed.stdout

def test_ssm_audit_protected_main_guard_executes_offline(tmp_path):
    """Exercise the actual pre-OIDC shell, not a mocked Python reimplementation."""
    import os
    import subprocess

    workflow = Path(".github/workflows/audit-cloud-independent-runtime.yml").read_text(
        encoding="utf-8"
    )
    guard = workflow.split(
        "      - name: Verify protected main and checkout before AWS OIDC\n", 1
    )[1].split("      - name: Configure temporary GitHub OIDC credentials", 1)[0]
    script = guard.split("        run: |\n", 1)[1]
    script = "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in script.splitlines()
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_gh = fake_bin / "gh"
    fake_git.write_text(
        '#!/bin/sh\n'
        '[ "$1" = rev-parse ] && [ "$2" = HEAD ] || exit 4\n'
        'printf "%s\n" "$TEST_CHECKOUT_SHA"\n',
        encoding="utf-8",
    )
    fake_gh.write_text(
        '#!/bin/sh\n'
        '[ "$1" = api ] || exit 4\n'
        '[ "$TEST_GH_FAIL" != YES ] || exit 5\n'
        'printf "%s\n" "$TEST_MAIN_SHA"\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    fake_gh.chmod(0o755)
    sha = "a" * 40
    env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ["PATH"],
               GITHUB_REF="refs/heads/main", GITHUB_SHA=sha,
               GITHUB_REPOSITORY="kaku3030/stock-razor", TEST_CHECKOUT_SHA=sha,
               TEST_MAIN_SHA=sha, TEST_GH_FAIL="NO", GH_TOKEN="fixture-only")
    cases = [
        ({}, 0, ""),
        ({"GITHUB_REF": "refs/heads/research"}, 2, "AUDIT_NON_MAIN_REF_BLOCKED"),
        ({"TEST_CHECKOUT_SHA": "b" * 40}, 2, "AUDIT_CHECKOUT_SHA_MISMATCH"),
        ({"GITHUB_SHA": "invalid"}, 2, "AUDIT_CHECKOUT_SHA_MISMATCH"),
        ({"TEST_MAIN_SHA": "b" * 40}, 2, "AUDIT_MAIN_MOVED_ABORT"),
        ({"TEST_GH_FAIL": "YES"}, 2, "AUDIT_MAIN_LOOKUP_BLOCKED"),
    ]
    for overrides, expected_code, marker in cases:
        result = subprocess.run(
            ["bash", "-c", script], env={**env, **overrides},
            text=True, capture_output=True, timeout=5, check=False,
        )
        assert result.returncode == expected_code, (overrides, result.stderr)
        if marker:
            assert marker in result.stderr
        assert "fixture-only" not in (result.stdout + result.stderr)


def test_ssm_audit_rechecks_main_before_remote_execution():
    source = Path(".github/workflows/audit-cloud-independent-runtime.yml").read_text(
        encoding="utf-8"
    )
    before_iam = source.index("AUDIT_MAIN_MOVED_ABORT")
    aws_oidc = source.index("      - name: Configure temporary GitHub OIDC credentials")
    pre_ssm = source.index("AUDIT_PRE_SSM_MAIN_MOVED_ABORT")
    remote_call = source.index("aws ssm send-command")
    assert before_iam < aws_oidc < pre_ssm < remote_call
    assert source.count("GH_TOKEN: ${{ github.token }}") == 2
    assert "persist-credentials: false" in source
    assert "AUDIT_PRE_SSM_MAIN_LOOKUP_BLOCKED" in source
