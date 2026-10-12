"""Synthetic WS background-worker diagnostics, never provider/network I/O."""
import json
from pathlib import Path
import threading

import pytest

from scripts import probe_tickflow_isolated as probe
from tests.test_tickflow_isolated_qualification_probe import FakeClient


def _observe(monkeypatch, thread=None):
    client = FakeClient()
    if thread is not None:
        client.stream._thread = thread
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    return probe.build_probe(
        mode="premium",
        symbols=("159611.SZ", "518880.SH"),
        ws_seconds=1,
        client_factory=lambda: client,
        credential_present=True,
    )["operations"][-1]


def test_unobservable_sdk_worker_never_implies_real_connection(monkeypatch):
    ws = _observe(monkeypatch)
    assert ws["background_thread_state"] == "UNOBSERVABLE"
    assert ws["background_thread_not_provider_connection_proof"] is True
    assert ws["connection_call"] == "PASS"
    assert ws["connection_state"] == "UNKNOWN"
    assert ws["continuous_feed_qualified"] is False


def test_dead_sdk_background_thread_is_distinguished_from_no_callbacks(monkeypatch):
    dead = threading.Thread(target=lambda: None)
    ws = _observe(monkeypatch, dead)
    assert ws["background_thread_state"] == "STOPPED"
    assert ws["connection_call"] == "PASS"
    assert ws["connection_state"] == "UNKNOWN"
    assert ws["radar_admission"] if "radar_admission" in ws else True


def test_alive_thread_is_not_connected_provider_ack(monkeypatch):
    gate = threading.Event()
    thread = threading.Thread(target=lambda: gate.wait(10), daemon=True)
    thread.start()
    try:
        ws = _observe(monkeypatch, thread)
        assert ws["background_thread_state"] == "ALIVE"
        assert ws["subscription_state"] == "UNKNOWN"
        assert ws["connection_state"] == "UNKNOWN"
        assert ws["subscribed_ack_evidence"] == "NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK"
        assert ws["continuous_feed_qualified"] is False
    finally:
        gate.set()
        thread.join(timeout=2)


def test_aws_and_actions_publish_only_known_enum_and_never_call_it_connection():
    bootstrap=Path("ops/aws/run_tickflow_premium_probe.sh").read_text(encoding="utf-8")
    gha=Path(".github/workflows/probe-tickflow-aws-premium.yml").read_text(encoding="utf-8")
    audit=Path(".github/workflows/audit-existing-tickflow-quote-cache.yml").read_text(encoding="utf-8")
    assert 'if state in ("ALIVE","STOPPED","UNOBSERVABLE")' in bootstrap
    assert 'item["background_thread_not_provider_connection_proof"]=True' in bootstrap
    assert 'record["background_thread_not_provider_connection_proof"]=True' in gha
    assert 'assert item.get("background_thread_not_provider_connection_proof") is True' in gha
    assert 'ws_background_thread_state' in audit
    assert 'WS_THREAD_PROVENANCE_UNKNOWN' in audit
    assert '"ws_provider_live_qualified":False' in audit
    assert "echo \"$out\"" not in gha
