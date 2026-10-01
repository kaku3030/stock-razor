"""Build the Research-only persisted Observation Ledger calibration artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.strategy_lab.opportunity_cost import DATASET_CONTRACT_VERSION, HARNESS_VERSION, calibration_summary
from src.services.strategy_lab.persisted_observation_replay import load_replay_inputs

DATASET_ID = "persisted-observation-replay-v0.1"
SOURCE_TYPE = "CAPTURED_TEST_REPLAY"
SOURCE_COMMIT = "51248081e6dff119e44a9cdafe0ecea6996e892f"


def build_persisted_baseline(root: Path) -> dict:
    observations, truths = load_replay_inputs(
        root / "research/artifacts/persisted-replay-observations-v0.1.jsonl",
        root / "research/artifacts/persisted-replay-truths-v0.1.jsonl",
    )
    baseline = calibration_summary(observations, truths, dataset_id=DATASET_ID)
    baseline["dq_unknown_count"] = sum(item is None for item in (baseline["time_to_capture"]["p50"],))
    baseline["time_to_capture"]["status"] = "UNKNOWN" if baseline["time_to_capture"]["p50"] is None else "KNOWN"
    baseline["execution_metrics_status"] = "UNKNOWN_NO_PERSISTED_EXECUTION_RECORDS"
    return {
        "dataset_contract": {
            "contract_version": DATASET_CONTRACT_VERSION, "dataset_id": DATASET_ID,
            "source_type": SOURCE_TYPE, "market": "UNKNOWN",
            "time_range": {"start": None, "end": None, "status": "UNKNOWN"},
            "universe_definition": "captured-test-universe-v0.1", "truth_definition_version": "truth-v0.1",
            "harness_version": HARNESS_VERSION, "source_commit": SOURCE_COMMIT,
            "record_counts": {"observations": len(observations), "truths": len(truths), "opportunities": sum(item.status.value == "OPPORTUNITY" and not item.censored for item in truths)},
            "dq_caveats": [
                "Captured test replay; not production or Shadow market history",
                "No source_event_at, decision_available_at, or persisted execution/fill timestamps",
                "TTC and execution metrics are UNKNOWN; sample is not statistically reliable",
            ],
        },
        "baseline": baseline,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build_persisted_baseline(args.root), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if args.write:
        args.write.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
