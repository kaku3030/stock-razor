import json

import pytest
from unittest.mock import MagicMock

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.services.stock_radar_v2.observation_assembly import (
    ASSEMBLY_CONTRACT_VERSION,
    ShadowObservationIdentity,
    assemble_shadow_observation,
)
from src.services.stock_radar_v2.observation_ledger import ObservationCaptureWriter
from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext


def test_identity_is_canonical_and_deterministic():
    left = ShadowObservationIdentity("run-1", "ABC").observation_id()
    right = ShadowObservationIdentity("run-1", "ABC").observation_id()
    assert left == right and left.startswith("sha256:")


def test_retry_is_idempotent_and_conflicting_duplicate_fails_loud(tmp_path):
    path = tmp_path / "observations.jsonl"
    writer = ObservationCaptureWriter(path)
    dashboard = {"decision_type": "buy"}
    first = assemble_shadow_observation(run_id="run-1", instrument="ABC", dashboard=dashboard, writer=writer)
    second = assemble_shadow_observation(run_id="run-1", instrument="ABC", dashboard=dashboard, writer=writer)
    assert first == second
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(ValueError, match="conflicting observation"):
        writer.append(first.__class__(first.observation_id, "OTHER"), source_type=ASSEMBLY_CONTRACT_VERSION, instrument="ABC", provenance={})


def test_missing_runtime_facts_and_timestamps_stay_unknown(tmp_path):
    observation = assemble_shadow_observation(
        run_id="run-1",
        instrument="ABC",
        dashboard={"portfolio_admissible": True, "execution_feasible": True, "canonical_permission": "ALLOW"},
        writer=ObservationCaptureWriter(tmp_path / "o.jsonl"),
    )
    assert observation.portfolio_admissible is None
    assert observation.execution_feasible is None
    assert observation.execution_record_id is None
    assert observation.canonical_permission == "UNKNOWN"
    assert observation.decision_available_at is None
    assert observation.latency.source_event_at is None


def test_supplied_timestamps_preserve_pit_order_without_fabrication(tmp_path):
    observation = assemble_shadow_observation(
        run_id="run-1",
        instrument="ABC",
        dashboard={},
        timestamps={"decision_available_at": 10, "detected_at": 9},
        writer=ObservationCaptureWriter(tmp_path / "o.jsonl"),
    )
    assert observation.decision_available_at == 10
    assert observation.latency.detected_at == 9
    record = json.loads((tmp_path / "o.jsonl").read_text(encoding="utf-8"))
    assert record["timestamps"]["source_event_at"] is None


def test_orchestrator_seam_captures_only_after_explicit_final_boundary(tmp_path):
    writer = ObservationCaptureWriter(tmp_path / "o.jsonl")
    orchestrator = AgentOrchestrator(MagicMock(), MagicMock(), observation_writer=writer)
    ctx = AgentContext(query="test", stock_code="ABC")
    ctx.meta["run_id"] = "run-1"
    dashboard = {"decision_type": "buy"}
    orchestrator._capture_shadow_observation(ctx, dashboard)
    assert ctx.meta["shadow_observation_id"].startswith("sha256:")
    assert json.loads((tmp_path / "o.jsonl").read_text(encoding="utf-8"))["canonical_permission"] == "UNKNOWN"


def test_writer_io_failure_does_not_change_frozen_dashboard():
    writer = MagicMock()
    writer.append.side_effect = OSError("ledger unavailable")
    orchestrator = AgentOrchestrator(MagicMock(), MagicMock(), observation_writer=writer)
    ctx = AgentContext(query="test", stock_code="ABC")
    ctx.meta["run_id"] = "run-1"
    orchestrator._capture_shadow_observation(ctx, {"decision_type": "buy"})
    assert "OSError" in ctx.meta["shadow_observation_capture_error"]
