"""Read bounded categorical AI runtime telemetry; never instantiate a backend."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.stock_radar_v2.ai_consumer_runtime import assess_runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--worker-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args(argv)
    verdict = {"status": "UNKNOWN", "research_only": True, "radar_admission": "BLOCKED",
               "live_trade": False, "cost_status": "UNKNOWN", "cloud_acceptance": "NOT_VERIFIED"}
    try:
        with args.status_file.open("rb") as handle:
            body = handle.read(65537)
        if len(body) > 65536:
            raise ValueError("status exceeds limit")
        verdict = assess_runtime(json.loads(body), expected_worker_sha=args.worker_sha,
            expected_source_sha=args.source_sha, now=datetime.now(timezone.utc))
    except (OSError, ValueError, TypeError, KeyError):
        pass
    print(json.dumps(verdict, sort_keys=True, allow_nan=False))
    return 0 if verdict["status"] in {"OBSERVED", "BUSY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
