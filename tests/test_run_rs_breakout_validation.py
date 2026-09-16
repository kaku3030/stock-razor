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

    result = run_validation(tmp_path, config, output, seed=7, round_trip_cost_bps=100.0)

    assert result["schema"] == "radar-rs-breakout-validation-v0.1"
    assert result["status"] == "RESEARCH_ONLY"
    assert result["guard"]["pit"] == "RECORDED_CAPTURE_ONLY"
    assert result["guard"]["signal_execution"] == "NEXT_BAR_OPEN"
    assert result["guard"]["future_data_used_for_signal"] is False
    assert result["guard"]["never_seen_holdout"] == "PROTECTED"
    assert result["guard"]["consumes_holdout"] is False
    assert result["guard"]["round_trip_cost_bps"] == 100.0
    overall = result["metrics"]["WITH_RULE"]["overall"]
    assert overall["round_trip_cost_bps"] == 100.0
    assert overall["average_net_forward_return"] < overall["average_forward_return"]
    assert overall["net_win_rate"] <= overall["win_rate"]
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


def test_runner_rejects_duplicate_capture_date(tmp_path: Path) -> None:
    _write_capture(tmp_path, "us_aaa", "AAA")
    _write_capture(tmp_path, "us_bbb", "BBB")
    path = tmp_path / "us_aaa.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[-1][1] = rows[1][1]
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    (tmp_path / "us_aaa.csv.manifest.json").write_text(
        json.dumps({
            "status": "CAPTURED_NOT_APPROVED",
            "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )
    config = tmp_path / "contract.json"
    _write_contract(config)

    with pytest.raises(ValidationError, match="duplicate date/symbol"):
        run_validation(tmp_path, config, tmp_path / "out.json")


def test_runner_rejects_mixed_symbols(tmp_path: Path) -> None:
    _write_capture(tmp_path, "us_aaa", "AAA")
    _write_capture(tmp_path, "us_bbb", "BBB")
    path = tmp_path / "us_aaa.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[2][0] = "OTHER"
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    (tmp_path / "us_aaa.csv.manifest.json").write_text(
        json.dumps({
            "status": "CAPTURED_NOT_APPROVED",
            "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )
    config = tmp_path / "contract.json"
    _write_contract(config)

    with pytest.raises(ValidationError, match="mixed symbols in capture"):
        run_validation(tmp_path, config, tmp_path / "out.json")


def test_runner_rejects_empty_eligible_window(tmp_path: Path) -> None:
    _write_capture(tmp_path, "us_aaa", "AAA", days=25)
    _write_capture(tmp_path, "us_bbb", "BBB", days=25)
    config = tmp_path / "contract.json"
    _write_contract(config)

    with pytest.raises(ValidationError, match="no eligible observations"):
        run_validation(tmp_path, config, tmp_path / "out.json")


def test_runner_rejects_inconsistent_ohlc(tmp_path: Path) -> None:
    _write_capture(tmp_path, "us_aaa", "AAA")
    _write_capture(tmp_path, "us_bbb", "BBB")
    path = tmp_path / "us_aaa.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1][3] = rows[1][4]
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    (tmp_path / "us_aaa.csv.manifest.json").write_text(
        json.dumps({
            "status": "CAPTURED_NOT_APPROVED",
            "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )
    config = tmp_path / "contract.json"
    _write_contract(config)

    with pytest.raises(ValidationError, match="inconsistent OHLC"):
        run_validation(tmp_path, config, tmp_path / "out.json")


def test_runner_rejects_empty_symbol(tmp_path: Path) -> None:
    _write_capture(tmp_path, "us_aaa", "AAA")
    _write_capture(tmp_path, "us_bbb", "BBB")
    path = tmp_path / "us_aaa.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1][0] = " "
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    (tmp_path / "us_aaa.csv.manifest.json").write_text(
        json.dumps({
            "status": "CAPTURED_NOT_APPROVED",
            "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )
    config = tmp_path / "contract.json"
    _write_contract(config)

    with pytest.raises(ValidationError, match="empty symbol"):
        run_validation(tmp_path, config, tmp_path / "out.json")


def test_runner_supports_execution_delay_stress(tmp_path: Path) -> None:
    for index, symbol in enumerate(("AAA", "BBB", "CCC")):
        _write_capture(tmp_path, f"us_{symbol.lower()}", symbol, days=70 + index)
    config = tmp_path / "contract.json"
    _write_contract(config)

    result = run_validation(tmp_path, config, tmp_path / "out.json", execution_delay_bars=2)

    assert result["guard"]["execution_delay_bars"] == 2
    assert result["guard"]["signal_execution"] == "DELAYED_OPEN_2_BARS"
    assert result["observation_count"] < 132
