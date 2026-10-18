import json
from pathlib import Path

from scripts.import_vibe_trading_research import import_run


def _run_dir(tmp_path: Path, *, validation=None, friction=None) -> Path:
    root = tmp_path / "vibe-run"
    (root / "artifacts").mkdir(parents=True)
    (root / "config.json").write_text(json.dumps({"source": "local"}), encoding="utf-8")
    card = {"run_id": "run-1"}
    if validation is not None:
        card["validation"] = validation
    if friction is not None:
        card["execution_friction"] = friction
    (root / "run_card.json").write_text(json.dumps(card), encoding="utf-8")
    (root / "artifacts" / "equity.csv").write_text("timestamp,equity\n2026-01-01,100\n", encoding="utf-8")
    (root / "artifacts" / "trades.csv").write_text("timestamp,code,side,price,qty\n", encoding="utf-8")
    return root


def test_import_is_read_only_and_fail_closed(tmp_path: Path) -> None:
    result = import_run(_run_dir(tmp_path))
    assert result["status"] == "RESEARCH_ONLY"
    assert result["data"]["provider_finality"] == "UNKNOWN"
    assert result["validation"]["oos"] == "NOT_VERIFIED"
    assert result["validation"]["cost_sensitivity"] == "UNKNOWN_MISSING_EXPLICIT_FRICTION"
    assert result["safety"]["radar_admission"] == "BLOCKED"
    assert result["safety"]["trade_execution"] == "NO"


def test_declarations_alone_do_not_pass(tmp_path: Path) -> None:
    result = import_run(_run_dir(tmp_path, validation={"oos_status": "OOS_VALIDATED"}, friction={"commission_bps": 0}))
    assert result["validation"]["oos"] == "NOT_VERIFIED"
    assert result["validation"]["cost_sensitivity"] == "UNKNOWN_MISSING_EXPLICIT_FRICTION"


def test_governed_oos_and_complete_friction_can_pass(tmp_path: Path) -> None:
    result = import_run(_run_dir(tmp_path, validation={"oos_status": "OOS_VALIDATED", "holdout": {"status": "GOVERNED", "dataset_hash": "sha256:holdout", "strategy_not_tuned_on_holdout": True}}, friction={"commission_bps": 1.0, "slippage_bps": 2.0}))
    assert result["validation"]["oos"] == "OOS_VALIDATED"
    assert result["validation"]["cost_sensitivity"] == "PASS"


def test_missing_run_card_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "vibe-run"
    root.mkdir()
    (root / "config.json").write_text("{}", encoding="utf-8")
    try:
        import_run(root)
    except ValueError as exc:
        assert str(exc) == "Vibe run is missing run_card.json"
    else:
        raise AssertionError("missing run_card.json must block import")
