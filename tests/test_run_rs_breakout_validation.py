from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.run_rs_breakout_validation import ValidationError, run_validation


def _write_capture(root: Path, stem: str, symbol: str, days: int = 70) -> None:
    path = root / f"{stem}.csv"
    start = date(2020, 1, 1)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
        for index in range(days):
            close = 100.0 + index * (index + 1) * 0.05
            writer.writerow([
                symbol,
                (start + timedelta(days=index)).isoformat(),
                f"{close:.4f}",
                f"{close + 1:.4f}",
                f"{close - 1:.4f}",
                f"{close:.4f}",
                1000 + index * 25,
            ])
    (root / f"{stem}.csv.manifest.json").write_text(
        json.dumps({
            "status": "CAPTURED_NOT_APPROVED",
            "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )


def _write_contract(path: Path) -> None:
    path.write_text(json.dumps({
        "schema": "radar-rs-breakout-hypothesis-v0.1",
        "rule_id": "oliver-kell-rs-breakout",
        "status": "RESEARCH_ONLY",
        "provenance": {"production_authorized": False},
        "parameters": {
            "breakout_window_bars": 20,
            "volume_multiple": 1.1,
            "relative_strength_percentile": 80,
            "holding_period_bars": 5,
        },
        "required_counterfactuals": [
            "WITH_RULE",
            "WITHOUT_RULE",
            "SHUFFLED_PLACEBO",
            "DELAYED_RULE",
            "REGIME_CONDITIONED",
        ],
        "holdout_policy": {"never_seen_holdout": "PROTECTED", "consumes_holdout": False},
    }), encoding="utf-8")


def test_runner_emits_independent_research_report(tmp_path: Path) -> None:
    for index, symbol in enumerate(("AAA", "BBB", "CCC")):
        _write_capture(tmp_path, f"us_{symbol.lower()}", symbol, days=70 + index)
    config = tmp_path / "contract.json"
    output = tmp_path / "out" / "validation.json"
    _write_contract(config)

    result = run_validation(tmp_path, config, output, seed=7)

    assert result["schema"] == "radar-rs-breakout-validation-v0.1"
    assert result["status"] == "RESEARCH_ONLY"
    assert result["guard"]["pit"] == "RECORDED_CAPTURE_ONLY"
    assert result["guard"]["future_data_used_for_signal"] is False
    assert result["guard"]["never_seen_holdout"] == "PROTECTED"
    assert result["guard"]["consumes_holdout"] is False
    assert set(result["metrics"]) == {
        "WITH_RULE", "WITHOUT_RULE", "SHUFFLED_PLACEBO",
        "DELAYED_RULE", "REGIME_CONDITIONED",
    }
    assert set(result["metrics"]["WITH_RULE"]["splits"]) == {
        "development", "validation", "never_seen_holdout",
    }
    assert output.is_file()


def test_runner_fails_closed_on_unapproved_capture(tmp_path: Path) -> None:
    _write_capture(tmp_path, "us_aaa", "AAA")
    _write_capture(tmp_path, "us_bbb", "BBB")
    manifest = tmp_path / "us_aaa.csv.manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["status"] = "APPROVED"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    config = tmp_path / "contract.json"
    _write_contract(config)

    with pytest.raises(ValidationError, match="not recorded evidence"):
        run_validation(tmp_path, config, tmp_path / "out.json")
