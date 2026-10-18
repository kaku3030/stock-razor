"""Import a Vibe-Trading backtest run as Stock Razor research evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any

VIBE_REPOSITORY = "HKUDS/Vibe-Trading"
ADAPTER_SCHEMA = "stock-razor-vibe-trading-import-v0.1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _has_explicit_friction(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        isinstance(value.get(key), Real)
        and not isinstance(value.get(key), bool)
        and math.isfinite(float(value[key]))
        and float(value[key]) >= 0
        for key in ("commission_bps", "slippage_bps")
    )


def _has_governed_oos(validation: object) -> bool:
    if not isinstance(validation, dict) or validation.get("oos_status") != "OOS_VALIDATED":
        return False
    holdout = validation.get("holdout")
    return (
        isinstance(holdout, dict)
        and holdout.get("status") == "GOVERNED"
        and isinstance(holdout.get("dataset_hash"), str)
        and bool(holdout["dataset_hash"].strip())
        and holdout.get("strategy_not_tuned_on_holdout") is True
    )


def import_run(run_dir: Path) -> dict[str, Any]:
    root = run_dir.resolve()
    config_path = root / "config.json"
    card_path = root / "run_card.json"
    if not config_path.is_file():
        raise ValueError("Vibe run is missing config.json")
    if not card_path.is_file():
        raise ValueError("Vibe run is missing run_card.json")
    config = _read_json(config_path)
    card = _read_json(card_path)
    artifacts_dir = root / "artifacts"
    paths = {"equity": artifacts_dir / "equity.csv", "trades": artifacts_dir / "trades.csv", "metrics": artifacts_dir / "metrics.csv"}
    source = str(config.get("source") or "UNKNOWN").strip() or "UNKNOWN"
    files = [{"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)} for path in (config_path, card_path, *paths.values()) if path.is_file()]
    return {
        "schema_version": ADAPTER_SCHEMA,
        "status": "RESEARCH_ONLY",
        "source_repository": VIBE_REPOSITORY,
        "vibe_version": card.get("version") or card.get("app_version") or "UNKNOWN",
        "run_id": card.get("run_id") or card.get("id") or "UNKNOWN",
        "data": {"source": source, "local_only": source == "local", "provider_finality": "UNKNOWN", "time_zone": "UNKNOWN", "calendar": "UNKNOWN", "artifact_status": {name: "PASS" if path.is_file() else "UNKNOWN_MISSING" for name, path in paths.items()}},
        "validation": {"oos": "OOS_VALIDATED" if _has_governed_oos(card.get("validation")) else "NOT_VERIFIED", "cost_sensitivity": "PASS" if _has_explicit_friction(card.get("execution_friction")) else "UNKNOWN_MISSING_EXPLICIT_FRICTION", "research_admission": "RESEARCH_CANDIDATE"},
        "safety": {"paid_service_used": False if source == "local" else None, "mcp_started": False, "live_trade": False, "paper_auto_ready": False, "radar_admission": "BLOCKED", "trade_execution": "NO"},
        "provenance": {"run_dir": str(root), "config": config, "run_card_keys": sorted(card.keys()), "files": files},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()
    payload = json.dumps(import_run(args.run_dir), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
