"""Exercise the actual OpenD file publishers, including embedded heartbeat code."""

import ast
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import threading

import pytest

from src.services.live_feed.canonical_snapshot_export import write_canonical_snapshot_export
from src.services.live_feed.futu_us_daily_history import write_futu_us_daily_history


def heartbeat_writer(path, payload):
    source = (Path(__file__).resolve().parents[1] / "ops/aws/install_us_opend_livefeed.sh").read_text()
    source = source.split('cat >"$INSTALL_ROOT/run.py" <<\'PY\'\n', 1)[1].split('\nPY\n', 1)[0]
    tree = ast.parse(source)
    # Load only the publication seam; no Futu connection or provider requests.
    nodes = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
             and (isinstance(n, ast.Import) and all(a.name in {"json", "os"} for a in n.names)
                  or isinstance(n, ast.ImportFrom) and n.module == "src.services.live_feed.runtime_publication")]
    nodes += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "publish"]
    namespace = {"os": os, "json": json, "status_path": str(path)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "heartbeat-publication", "exec"), namespace)
    namespace["publish"](payload)


WRITERS = [write_canonical_snapshot_export, write_futu_us_daily_history, heartbeat_writer]


@pytest.mark.parametrize("writer", WRITERS)
def test_concurrent_publishers_use_independent_temporary_files(tmp_path, monkeypatch, writer):
    path = tmp_path / "runtime.json"
    barrier = threading.Barrier(2)
    real_fsync = os.fsync

    def synchronized_fsync(fd):
        real_fsync(fd)
        if stat.S_ISREG(os.fstat(fd).st_mode):
            barrier.wait(timeout=5)

    monkeypatch.setattr(os, "fsync", synchronized_fsync)
    values = [{"sequence": i, "data": str(i) * 10000} for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(writer, path, value) for value in values]
        for future in futures:
            future.result(timeout=10)
    assert json.loads(path.read_text()) in values


@pytest.mark.parametrize("writer", WRITERS)
def test_serialization_failure_preserves_last_good_file(tmp_path, writer):
    path = tmp_path / "runtime.json"
    writer(path, {"sequence": 1})
    with pytest.raises(ValueError):
        writer(path, {"invalid": float("nan")})
    assert json.loads(path.read_text()) == {"sequence": 1}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("writer", WRITERS)
def test_permission_failure_propagates_and_cleans_up(tmp_path, monkeypatch, writer):
    path = tmp_path / "runtime.json"
    writer(path, {"sequence": 1})

    def denied(*args):
        raise PermissionError("injected replace denial")

    monkeypatch.setattr(os, "replace", denied)
    with pytest.raises(PermissionError):
        writer(path, {"sequence": 2})
    assert json.loads(path.read_text()) == {"sequence": 1}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("writer", WRITERS)
def test_missing_or_corrupt_publication_is_replaced_without_reusing_old_temp(tmp_path, writer):
    path = tmp_path / "recreated" / "runtime.json"
    writer(path, {"sequence": 1})
    path.unlink()
    writer(path, {"sequence": 2})
    path.write_text("{broken")
    writer(path, {"sequence": 3})
    assert json.loads(path.read_text()) == {"sequence": 3}


@pytest.mark.parametrize("writer", WRITERS)
def test_interrupted_write_is_not_reused_by_next_publication(tmp_path, writer):
    path = tmp_path / "runtime.json"
    writer(path, {"sequence": 1})
    # A process killed before replace may leave staging bytes. A new process
    # must neither publish them nor clobber another in-flight writer's staging.
    orphan = tmp_path / ".runtime.json.interrupted.tmp"
    orphan.write_text('{"partial":')
    writer(path, {"sequence": 2})
    assert json.loads(path.read_text()) == {"sequence": 2}
    assert orphan.read_text() == '{"partial":'


@pytest.mark.parametrize("writer", WRITERS)
def test_failed_file_flush_preserves_last_good_publication(tmp_path, monkeypatch, writer):
    path = tmp_path / "runtime.json"
    writer(path, {"sequence": 1})

    def io_failure(fd):
        raise OSError("injected disk failure")

    monkeypatch.setattr(os, "fsync", io_failure)
    with pytest.raises(OSError):
        writer(path, {"sequence": 2})
    assert json.loads(path.read_text()) == {"sequence": 1}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name != "posix", reason="POSIX service access modes")
@pytest.mark.parametrize("writer", WRITERS)
def test_reader_access_mode_preserved(tmp_path, writer):
    path = tmp_path / "runtime.json"
    writer(path, {"sequence": 1})
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    path.chmod(0o600)
    writer(path, {"sequence": 2})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
