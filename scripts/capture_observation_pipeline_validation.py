"""Validate the real Observation capture seam without claiming market history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.stock_radar_v2.observation_ledger import Observation, ObservationCaptureWriter


def capture_sample(path: Path) -> dict:
    observation = Observation(
        observation_id="capture-pipeline-validation-001",
        detector_status="UNKNOWN",
        evidence_ids=("CAPTURE_PIPELINE_VALIDATION",),
        canonical_permission="UNKNOWN",
    )
    writer = ObservationCaptureWriter(path)
    return writer.append(
        observation,
        source_type="CAPTURE_PIPELINE_VALIDATION",
        market=None,
        instrument=None,
        provenance={"source_ref": "real-observation-capture-v0.1", "runtime_version": None},
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(capture_sample(args.output), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
