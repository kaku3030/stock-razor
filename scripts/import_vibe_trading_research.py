"""Import a Vibe-Trading backtest run as Stock Razor research evidence.

This adapter is deliberately offline and read-only. It consumes only a
Vibe-Trading run directory; it does not start Vibe-Trading, fetch market data,
load an MCP server, call a paid provider, or place orders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def import_run(run_dir: Path) -> dict[str, Any]:
    """Return a fail-closed, JSON-safe evidence envelope for ``run_dir``."""
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
    equity_path = artifacts_dir / "equity.csv"
    trades_path = artifacts_dir / "trades.csv"
    metrics_path = artifacts_dir / "metrics.csv"

    source = str(config.get("source") or "UNKNOWN").strip() or "UNKNOWN"
    local_only = source == "local"
    validation = card.get("validation")
    oos_status = "NOT_VERIFIED"
    if isinstance(validation, dict):
        declared = validation.get("oos_status") or validation.get("status")
        if declared in {"OOS_VALIDATED", "BACKTEST_VALIDATED"}:
            oos_status = str(declared)

    artifact_status = {
        "equity": "PASS" if equity_path.is_file() else "UNKNOWN_MISSING",
        "trades": "PASS" if trades_path.is_file() else "UNKNOWN_MISSING",
        "metrics": "PASS" if metrics_path.is_file() else "UNKNOWN_MISSING",
    }
    friction_status = "UNKNOWN_MISSING_EXPLICIT_FRICTION"
    if isinstance(card.get("execution_friction"), dict):
        friction_status = "PASS"

    files = []
    for path in (config_path, card_path, equity_path, trades_path, metrics_path):
        if path.is_file():
            files.append({"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)})

    return {
        "schema_version": ADAPTER_SCHEMA,
        "status": "RESEARCH_ONLY",
        "source_repository": VIBE_REPOSITORY,
        "vibe_version": card.get("version") or card.get("app_version") or "UNKNOWN",
        "run_id": card.get("run_id") or card.get("id") or "UNKNOWN",
        "data": {
            "source": source,
            "local_only": local_only,
            "provider_finality": "UNKNOWN",
            "time_zone": "UNKNOWN",
            "calendar": "UNKNOWN",
            "artifact_status": artifact_status,
        },
        "validation": {
            "oos": oos_status,
            "cost_sensitivity": friction_status,
            "research_admission": "RESEARCH_CANDIDATE",
        },
        "safety": {
            "paid_service_used": False if local_only else None,
            "mcp_started": False,
            "live_trade": False,
            "paper_auto_ready": False,
            "radar_admission": "BLOCKED",
            "trade_execution": "NO",
        },
        "provenance": {
            "run_dir": str(root),
            "config": config,
            "run_card_keys": sorted(card.keys()),
            "files": files,
        },
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
