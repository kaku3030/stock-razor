"""The quote-only startup primitive must import in a stdlib-only interpreter."""

import ast
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_neutral_notification_helper_imports_without_site_packages():
    script = """
import sys
from src.utils.systemd_notify import notify_systemd
for name in ('yaml', 'pandas', 'numpy', 'pydantic', 'requests', 'litellm',
             'src.services.stock_radar_v2'):
    assert name not in sys.modules, name
assert notify_systemd.__module__ == 'src.utils.systemd_notify'
print('STDLIB_NOTIFY_IMPORT=PASS')
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", script], cwd=ROOT,
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "STDLIB_NOTIFY_IMPORT=PASS"


def test_installer_smoke_and_embedded_runtime_use_neutral_path():
    source = (ROOT / "ops/aws/install_us_opend_livefeed.sh").read_text()
    expected = "from src.utils.systemd_notify import notify_systemd"
    before, runtime = source.split('cat >"$INSTALL_ROOT/run.py" <<\'PY\'\n', 1)
    assert expected in before
    assert expected in runtime.split("\nPY\n", 1)[0]
    assert "from src.services.stock_radar_v2.systemd_notify import" not in source
    smoke = before.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    for script in (smoke, runtime.split("\nPY\n", 1)[0]):
        statement = next(
            node for node in ast.parse(script).body
            if isinstance(node, ast.ImportFrom)
            and any(alias.name == "notify_systemd" for alias in node.names)
        )
        result = subprocess.run(
            [sys.executable, "-S", "-c", ast.unparse(statement)], cwd=ROOT,
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_legacy_radar_notification_path_reexports_same_primitive():
    from src.utils.systemd_notify import notify_systemd
    from src.services.stock_radar_v2.systemd_notify import notify_systemd as legacy

    assert legacy is notify_systemd
