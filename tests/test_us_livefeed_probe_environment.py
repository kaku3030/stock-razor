"""Probe environment must not impersonate a failed OpenD handshake."""
import json
import os
from pathlib import Path
import subprocess
import sys


import pytest

from scripts import us_livefeed_runtime_diagnostics as diag


@pytest.mark.parametrize("home_mode", ["missing", "empty", "present"])
def test_offline_probe_survives_sdk_logger_home_requirement(tmp_path, home_mode):
    # Real child import side effect; no provider context or socket exists.
    package = tmp_path / "futu"
    package.mkdir()
    (package / "__init__.py").write_text(
        "import os\n"
        "os.environ['HOME']\n"
        "__version__='10.11.7108'\n"
        "RET_OK=0\n"
        "class SysConfig:\n"
        " get_client_ver=staticmethod(lambda:1011)\n"
        " get_client_id=staticmethod(lambda:'synthetic')\n"
        " get_proto_fmt=staticmethod(lambda:0)\n"
        "class OpenQuoteContext:\n"
        " def __init__(self,*a,**k): raise AssertionError('network context forbidden')\n"
    )
    quote = package / "quote"
    quote.mkdir()
    (quote / "__init__.py").write_text("")
    (quote / "quote_query.py").write_text(
        "class InitConnect:\n"
        " @staticmethod\n"
        " def pack_req(**kw): return (0,'',b'packet')\n"
    )
    google = tmp_path / "google"
    google.mkdir()
    (google / "__init__.py").write_text("")
    protobuf = google / "protobuf"
    protobuf.mkdir()
    (protobuf / "__init__.py").write_text("__version__='7.36.2'\n")
    env = dict(os.environ)
    env.pop("HOME", None)
    if home_mode != "missing":
        env["HOME"] = str(tmp_path) if home_mode == "present" else ""
    env["PYTHONPATH"] = str(tmp_path)
    child = subprocess.run([sys.executable, "-c", diag.OFFLINE_INIT_PACK_CODE],
                           env=env, cwd=tmp_path, capture_output=True,
                           text=True, timeout=5)
    assert child.returncode == 0
    result = json.loads(child.stdout)
    assert result["offline_init_pack"] == "PASS"
    assert result["offline_home"] == ("PRESENT" if home_mode == "present" else "DEFAULTED")
    assert result["offline_stage"] == "COMPLETE"
    assert str(Path.home()) not in child.stdout
    assert child.stderr == ""


def test_offline_failure_retains_stage_but_never_exception_key(tmp_path):
    (tmp_path / "futu.py").write_text("raise KeyError('PRIVATE_VALUE')\n")
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    child = subprocess.run([sys.executable, "-c", diag.OFFLINE_INIT_PACK_CODE],
                           env=env, cwd=tmp_path, capture_output=True,
                           text=True, timeout=5)
    result = json.loads(child.stdout)
    assert result["offline_init_pack"] == "KEY_ERROR"
    assert result["offline_stage"] == "IMPORT_SDK"
    assert "PRIVATE_VALUE" not in child.stdout


def test_new_probe_fields_survive_public_projection_and_reject_values():
    from scripts.sanitize_ssm_probe_output import project
    raw = {"runtime_diagnostics": {"offline_home": "DEFAULTED",
           "offline_stage": "IMPORT_SDK", "offline_init_pack": "KEY_ERROR"}}
    projected = "\n".join(project(json.dumps(raw)))
    assert '"offline_home":"DEFAULTED"' in projected
    assert '"offline_stage":"IMPORT_SDK"' in projected
    assert diag.sanitize_runtime_diagnostics({
        "offline_home": "PRIVATE", "offline_stage": "PRIVATE"
    }).get("offline_stage") is None
