import json
from pathlib import Path

from scripts.import_vibe_trading_research import import_run


def _run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "vibe-run"
    (root / "artifacts").mkdir(parents=True)
    (root / "config.json").write_text(
        json.dumps({"source": "local", "codes": ["AAPL.US"], "start_date": "2026-01-01"}),
        encoding="utf-8",
    )
    (root / "run_card.json").write_text(json.dumps({"run_id": "run-1"}), encoding="utf-8")
    (root / "artifacts" / "equity.csv").write_text("timestamp,equity\n2026-01-01,100\n", encoding="utf-8")
    (root / "artifacts" / "trades.csv").write_text("timestamp,code,side,price,qty\n", encoding="utf-8")
    return root


def test_import_is_read_only_research_only_and_fail_closed(tmp_path: Path) -> None:
    result = import_run(_run_dir(tmp_path))

    assert result["status"] == "RESEARCH_ONLY"
    assert result["data"]["local_only"] is True
    assert result["data"]["provider_finality"] == "UNKNOWN"
    assert result["validation"]["oos"] == "NOT_VERIFIED"
    assert result["validation"]["cost_sensitivity"] == "UNKNOWN_MISSING_EXPLICIT_FRICTION"
    assert result["safety"]["live_trade"] is False
    assert result["safety"]["radar_admission"] == "BLOCKED"
    assert result["safety"]["trade_execution"] == "NO"


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
