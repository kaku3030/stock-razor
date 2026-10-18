import json
from pathlib import Path
import pytest
from datetime import timedelta

from src.services.stock_radar_v2.ai_consumer_runtime import run_ai_consumer, assess_runtime
from src.services.stock_radar_v2.bar_event_ledger import RadarBarEventLedger
from tests.test_stock_radar_v2_ai_event_consumer import NOW, SHA, Backend, event


def test_disabled_runtime_does_not_claim_and_reports_queue(tmp_path):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        result = run_ai_consumer(ledger, expected_source_sha=SHA, worker_sha=SHA,
            status_path=tmp_path / "status.json", stop_file=tmp_path / "STOP", now=lambda: NOW)
        assert result["phase"] == "DISABLED"
        assert result["queue"]["event_pending"] == 1
        assert ledger.get(saved.event.idempotency_key).attempts == 0


def test_monitor_marks_recorded_poll_as_stalled_after_deadline(tmp_path):
    snapshots = []
    class Observed(Backend):
        def generate(self, *args, **kwargs):
            import json
            snapshots.append(json.loads((tmp_path / "status.json").read_text()))
            return super().generate(*args, **kwargs)
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        ledger.record(event(), recorded_at=NOW)
        result = run_ai_consumer(ledger, backend=Observed(), enabled=True, expected_source_sha=SHA,
            worker_sha=SHA, status_path=tmp_path / "status.json", stop_file=tmp_path / "STOP", now=lambda: NOW)
        assert result["phase"] == "LIMIT_REACHED"
        assert result["queue"]["ai_succeeded"] == 1
        assert snapshots[0]["phase"] == "POLLING"
        verdict = assess_runtime(snapshots[0], expected_worker_sha=SHA, expected_source_sha=SHA,
                                 now=NOW + timedelta(seconds=91))
        assert verdict["status"] == "STALLED"


def runtime(ledger, tmp_path, **kwargs):
    return run_ai_consumer(ledger, expected_source_sha=SHA, worker_sha=SHA,
        status_path=tmp_path / "status.json", stop_file=tmp_path / "STOP", **kwargs)


@pytest.mark.parametrize("kind", ["file", "environment"])
def test_stop_before_dispatch_has_no_claim_or_model_call(tmp_path, monkeypatch, kind):
    if kind == "file": (tmp_path / "STOP").touch()
    else: monkeypatch.setenv("AUTONOMY_STOP", "true")
    backend = Backend()
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        result = runtime(ledger, tmp_path, backend=backend, enabled=True, now=lambda: NOW)
        assert result["phase"] == "STOPPED"
        assert ledger.get(saved.event.idempotency_key).attempts == 0
        assert result["queue"]["ai_started"] == 0
    assert backend.calls == []


def test_stop_during_call_keeps_completed_receipt(tmp_path):
    class Stops(Backend):
        def generate(self, *args, **kwargs):
            (tmp_path / "STOP").touch()
            return super().generate(*args, **kwargs)
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        ledger.record(event(), recorded_at=NOW)
        result = runtime(ledger, tmp_path, backend=Stops(), enabled=True, now=lambda: NOW)
        assert result["phase"] == "STOPPED" and result["queue"]["ai_succeeded"] == 1
        assert result["queue"]["event_acknowledged"] == 1


def test_status_write_failure_blocks_before_claim(tmp_path, monkeypatch):
    from src.services.stock_radar_v2 import ai_consumer_runtime as module
    backend = Backend()
    def fail(*args): raise OSError("private-path-and-secret")
    monkeypatch.setattr(module.os, "replace", fail)
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        with pytest.raises(RuntimeError, match="AI_RUNTIME_STATUS_WRITE_FAILED") as error:
            runtime(ledger, tmp_path, backend=backend, enabled=True, now=lambda: NOW)
        assert "private-path" not in str(error.value)
        assert ledger.get(saved.event.idempotency_key).attempts == 0
    assert backend.calls == [] and not (tmp_path / "status.json").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("tmp")]


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm"])
def test_status_path_cannot_replace_database_or_journal(tmp_path, suffix):
    path = tmp_path / "events.sqlite"
    with RadarBarEventLedger(path) as ledger:
        with pytest.raises(ValueError, match="must not replace"):
            run_ai_consumer(ledger, expected_source_sha=SHA, worker_sha=SHA,
                status_path=Path(str(path) + suffix), stop_file=tmp_path / "STOP")
        assert ledger.runtime_summary(now=NOW)["ai_started"] == 0


def test_unknown_result_halts_and_reopen_never_redispatches(tmp_path):
    def uncertain(*args): raise TimeoutError("private-provider-secret")
    backend, path = Backend(uncertain), tmp_path / "events.sqlite"
    with RadarBarEventLedger(path) as ledger:
        ledger.record(event(), recorded_at=NOW)
        result = runtime(ledger, tmp_path, backend=backend, enabled=True, max_cycles=10, now=lambda: NOW)
        assert result["phase"] == "HALTED" and result["queue"]["ai_unknown"] == 1
        assert assess_runtime(result, expected_worker_sha=SHA, expected_source_sha=SHA, now=NOW)["status"] == "BLOCKED"
    with RadarBarEventLedger(path) as ledger:
        runtime(ledger, tmp_path, backend=backend, enabled=True, now=lambda: NOW + timedelta(seconds=41))
    assert len(backend.calls) == 1
    assert "private-provider-secret" not in (tmp_path / "status.json").read_text()


def test_runtime_reopens_saved_receipt_and_ack_without_model_replay(tmp_path):
    path, backend = tmp_path / "events.sqlite", Backend()
    with RadarBarEventLedger(path) as ledger:
        ledger.record(event(), recorded_at=NOW)
        ledger.acknowledge = lambda *a, **k: (_ for _ in ()).throw(PermissionError("ACK interrupted"))
        first = runtime(ledger, tmp_path, backend=backend, enabled=True, now=lambda: NOW)
        assert first["consumer_status"] == "ACK_PENDING" and first["queue"]["ai_succeeded"] == 1
    with RadarBarEventLedger(path) as ledger:
        second = runtime(ledger, tmp_path, backend=backend, enabled=True, now=lambda: NOW + timedelta(seconds=200))
        assert second["consumer_status"] == "RECOVERED"
        assert second["queue"]["event_acknowledged"] == 1 and second["remaining_calls"] == 0
    assert len(backend.calls) == 1 and first["runtime_id"] != second["runtime_id"]


def test_runtime_requires_enough_remaining_budget_for_poll(tmp_path):
    backend = Backend()
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        ledger.record(event(), recorded_at=NOW)
        result = runtime(ledger, tmp_path, backend=backend, enabled=True,
                         max_runtime_seconds=1, now=lambda: NOW)
        assert result["phase"] == "LIMIT_REACHED" and result["queue"]["event_pending"] == 1
    assert backend.calls == []


def test_idle_loop_obeys_cycle_limit_and_finite_waits(tmp_path):
    ticks, waits = [0], []
    def wait(seconds):
        waits.append(seconds)
        ticks[0] += seconds
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        result = runtime(ledger, tmp_path, backend=Backend(), enabled=True, max_cycles=3,
            now=lambda: NOW + timedelta(seconds=ticks[0]), clock=lambda: ticks[0], wait=wait)
        assert result["phase"] == "LIMIT_REACHED" and result["consumer_status"] == "IDLE"
    assert waits == [1, 1]


def test_summary_does_not_change_expired_intent_or_lease(tmp_path):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        claim = ledger.claim_next(worker_id="old", now=NOW)
        ledger.begin_ai_wake(claim, now=NOW, timeout_seconds=1, max_calls=1)
        summary = ledger.runtime_summary(now=NOW + timedelta(seconds=2))
        assert summary["ai_expired"] == summary["ai_started"] == 1
        assert summary["ai_unknown"] == 0 and summary["event_claimed"] == 1
        assert ledger.get_ai_wake(saved.event.idempotency_key, now=NOW).status == "STARTED"


def status_payload(tmp_path):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        payload = runtime(ledger, tmp_path, now=lambda: NOW)
    payload["phase"] = "WAITING"
    return payload


@pytest.mark.parametrize("kind", ["worker_sha", "source_sha", "future", "unsafe", "bool_count", "invalid_date", "unknown_phase", "long_deadline"])
def test_monitor_rejects_unverified_or_forged_status(tmp_path, kind):
    p = status_payload(tmp_path)
    if kind == "worker_sha": p["worker_sha"] = "b" * 40
    if kind == "source_sha": p["expected_source_sha"] = "b" * 40
    if kind == "future": p["emitted_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if kind == "unsafe": p["live_trade"] = True
    if kind == "bool_count": p["queue"]["ai_unknown"] = False
    if kind == "invalid_date": p["emitted_at"] = "private-secret"
    if kind == "unknown_phase": p["phase"] = "private-secret"
    if kind == "long_deadline":
        p["phase"] = "POLLING"
        p["poll_deadline"] = (NOW + timedelta(seconds=100)).isoformat()
    result = assess_runtime(p, expected_worker_sha=SHA, expected_source_sha=SHA, now=NOW)
    assert result["status"] == "UNKNOWN"
    assert "private-secret" not in json.dumps(result)


def test_monitor_distinguishes_stale_backlog_and_deadletter(tmp_path):
    p = status_payload(tmp_path)
    assert assess_runtime(p, expected_worker_sha=SHA, expected_source_sha=SHA, now=NOW)["status"] == "OBSERVED"
    assert assess_runtime(p, expected_worker_sha=SHA, expected_source_sha=SHA, now=NOW + timedelta(seconds=61))["status"] == "STALE"
    p["queue"]["event_pending"] = 1
    p["queue"]["oldest_pending_at"] = (NOW - timedelta(seconds=121)).isoformat()
    assert assess_runtime(p, expected_worker_sha=SHA, expected_source_sha=SHA, now=NOW)["status"] == "DEGRADED"
    p["queue"]["event_pending"] = 0
    p["queue"]["oldest_pending_at"] = None
    p["queue"]["event_dead_letter"] = 1
    assert assess_runtime(p, expected_worker_sha=SHA, expected_source_sha=SHA, now=NOW)["status"] == "DEGRADED"


@pytest.mark.parametrize("body", [b"private-secret", b"x" * 65537, b'{"api_key":"private-secret"}'], ids=["invalid_json", "oversize", "unexpected_fields"])
def test_audit_cli_sanitizes_bad_status_without_provider_io(tmp_path, capsys, body):
    from scripts.audit_radar_ai_runtime import main
    path = tmp_path / "status.json"
    path.write_bytes(body)
    assert main(["--status-file", str(path), "--worker-sha", SHA, "--source-sha", SHA]) == 2
    result = capsys.readouterr().out
    assert "private-secret" not in result and json.loads(result)["status"] == "UNKNOWN"


def test_enabled_runtime_rejects_ephemeral_budget_storage(tmp_path):
    with RadarBarEventLedger(":memory:") as ledger:
        with pytest.raises(ValueError, match="persistent ledger required"):
            runtime(ledger, tmp_path, backend=Backend(), enabled=True, now=lambda: NOW)
