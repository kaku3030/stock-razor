from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def test_auto_200_symbol_filter_skips_rows_missing_active_flag(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    installer = (root / "ops/aws/install_cn_tickflow_research.sh").read_text(encoding="utf-8")
    match = re.search(r"<<'PY'\n(.*?)\nPY\n\)", installer, re.DOTALL)
    assert match is not None

    # The malformed short row reaches the active-flag column check. It must be
    # ignored, not crash the installer before the 200 valid entries are read.
    rows = [["000001.SZ", None, None, None, None, None, "CN", "stock"]]
    rows.extend(
        [f"{i:06d}.SZ", None, None, None, None, None, "CN", "stock", True]
        for i in range(1, 201)
    )
    index_path = tmp_path / "stocks.index.json"
    index_path.write_text(json.dumps(rows), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-c", match.group(1), str(index_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    symbols = result.stdout.strip().split(",")
    assert len(symbols) == 200
    assert symbols[0] == "000001.SZ"
    assert symbols[-1] == "000200.SZ"
