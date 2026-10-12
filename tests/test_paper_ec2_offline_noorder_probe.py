"""Offline-only AWS Paper smoke boundaries; all account IDs are synthetic."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import socket

import pytest

from scripts import probe_paper_ec2_offline_noorder as probe


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/probe-paper-ec2-isolated-noorder.yml"


def test_probe_fails_closed_for_non_pinned_runtime(tmp_path):
    x = probe.run_offline_cloud_soak(
        runtime_root=tmp_path, expected_sha="0" * 40,
    )
    assert x["runtime_sha"] == "NOT_VERIFIED"
    assert x["isolated_paper_restart"] == "NOT_VERIFIED"
    assert x["external_broker_orders"] == "NONE"
    assert x["paper_auto_ready"] == "NO"
    assert x["live_trade"] == "NO"


def test_cloud_hosted_paper_reopens_actual_temporary_sqlite_without_network(
    tmp_path, monkeypatch,
):
    mock_sha = "a" * 40
    monkeypatch.setattr(probe, "ALLOWED_RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=mock_sha + "\n"),
    )
    # The production probe blocks standard sockets before loading Paper code.
    # Preserve the original bound socket methods for later unrelated tests.
    monkeypatch.setattr(socket.socket, "connect", socket.socket.connect)
    monkeypatch.setattr(socket.socket, "connect_ex", socket.socket.connect_ex)
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)

    status = probe.run_offline_cloud_soak(
        runtime_root=tmp_path, expected_sha=mock_sha,
    )
    assert status["runtime_sha"] == "PASS"
    assert status["isolated_paper_restart"] == "PASS"
    assert status["duplicate_paper_intent_veto"] == "PASS"
    assert status["temporary_store_only"] == "YES"
    assert status["external_provider_calls"] == "NONE"
    assert status["external_broker_orders"] == "NONE"
    assert status["trade_execution"] == "NO"
    assert status["paper_auto_ready"] == "NO"
    assert not list(tmp_path.glob("*.sqlite"))


def test_aws_workflow_requires_manual_scope_and_never_dispatches_orders():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "approve_ephemeral_noorder_probe:" in source
    assert "default: false" in source
    assert "inputs.approve_ephemeral_noorder_probe == true" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "  push:" not in source
    assert "  schedule:" not in source
    assert "id-token: write" in source
    assert "StockRazorGitHubOpsRole" in source
    assert "AWS-RunShellScript" in source
    assert "persist-credentials: false" in source
    assert 'TRADE_EXECUTION: "NO"' in source
    assert 'PAPER_AUTO_READY: "NO"' in source
    assert "RAW_SSM_OUTPUT_WITHHELD=YES" in source
    assert "EXTERNAL_SIM_OR_LIVE_ORDERS=NONE" in source
    assert "secretsmanager:" not in source
    assert "place_order" not in source
    assert "cancel_order" not in source
    assert "unlock_trade" not in source
    assert "systemctl" not in source


def test_probe_synthetic_adapter_only_and_no_external_apis():
    text = (ROOT / "scripts/probe_paper_ec2_offline_noorder.py").read_text(encoding="utf-8")
    assert "create_paper_adapter()" in text
    assert "TemporaryDirectory" in text
    assert "socket.socket.connect = forbidden_connect" in text
    for name in ("import futu", "open_trade_context", "OpenSecTradeContext",
                 "requests.", "boto3", "secretsmanager", "place_order"):
        assert name not in text


def test_paper_ec2_allowed_host_path_still_rejects_wrong_installed_sha(
    tmp_path, monkeypatch,
):
    """A real directory alone must never satisfy the old-runtime proof."""
    monkeypatch.setattr(probe, "ALLOWED_RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(
        probe.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="b" * 40 + "\n",
        ),
    )
    result = probe.run_offline_cloud_soak(
        runtime_root=tmp_path, expected_sha="a" * 40,
    )
    assert result["runtime_sha"] == "NOT_VERIFIED"
    assert result["isolated_paper_restart"] == "NOT_VERIFIED"
    assert result["duplicate_paper_intent_veto"] == "NOT_VERIFIED"
    assert result["external_provider_calls"] == "NONE"
    assert result["external_broker_orders"] == "NONE"
    assert result["trade_execution"] == "NO"


def test_paper_ec2_factory_socket_escape_is_blocked_before_adapter_import(
    tmp_path, monkeypatch,
):
    """Never dial a network: a synthetic factory tries a trapped connect."""
    from src.services import execution_engine

    monkeypatch.setattr(probe, "ALLOWED_RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(
        probe.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="a" * 40 + "\n",
        ),
    )

    def trap_real_socket(*_args, **_kwargs):
        raise AssertionError("UNEXPECTED_NETWORK_SOCKET_ESCAPE")

    # Fail without touching the network even if production forgot to guard.
    monkeypatch.setattr(socket.socket, "connect", trap_real_socket)
    monkeypatch.setattr(socket.socket, "connect_ex", trap_real_socket)
    monkeypatch.setattr(socket, "create_connection", trap_real_socket)

    def attempting_paper_factory(*_args, **_kwargs):
        connection = socket.socket()
        try:
            connection.connect(("192.0.2.1", 443))
        finally:
            connection.close()

    monkeypatch.setattr(
        execution_engine, "create_paper_adapter", attempting_paper_factory,
    )
    with pytest.raises(RuntimeError, match="OFFLINE_NETWORK_FORBIDDEN"):
        probe.run_offline_cloud_soak(
            runtime_root=tmp_path, expected_sha="a" * 40,
        )
