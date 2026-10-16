"""Offline read-only contracts for the EC2 Feedback Hub storage probe."""
import json
import sqlite3
from pathlib import Path

from scripts import audit_feedback_hub_ec2_readonly as audit


DISK_MOUNT = "10 1 0:1 / / rw - ext4 /dev/fake rw\n"
VOLATILE_MOUNT = "10 1 0:1 / / rw - tmpfs tmpfs rw\n"


def _store(path: Path, *, schema_version="1"):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);"
            "CREATE TABLE feedback(id TEXT PRIMARY KEY, status TEXT, "
            "priority TEXT, evidence TEXT, source_ref TEXT);"
            "CREATE TABLE audit(sequence INTEGER PRIMARY KEY, "
            "event_id TEXT NOT NULL, payload TEXT);"
        )
        conn.execute(
            "INSERT INTO metadata(key,value) VALUES('schema_version',?)",
            (schema_version,),
        )
        conn.execute(
            "INSERT INTO feedback VALUES(?,?,?,?,?)",
            ("id-private", "NEW", "P0",
             '{"api_key":"do-not-export","raw_price":42.0}',
             "private-source-reference"),
        )
        conn.execute(
            "INSERT INTO audit VALUES(?,?,?)",
            (1, "synthetic-audit-id", '{"raw":"never-leak"}'),
        )


def test_observer_reads_valid_db_without_exposing_payload_or_writing(tmp_path, monkeypatch):
    path = tmp_path / "store.sqlite3"
    _store(path)
    monkeypatch.setattr(audit, "_path_allowed", lambda _: path)
    before = path.read_bytes()
    report = audit.observe(str(path), mountinfo=DISK_MOUNT)
    assert report["status"] == "READBACK_ONLY"
    assert report["existing_schema"] == "PASS"
    assert report["open_p0"] == 1
    assert report["open_p1"] == 0
    assert report["audit_count"] == 1
    assert len(report["audit_tail_digest"]) == 16
    assert report["cross_run_persistence"] == "NOT_VERIFIED"
    assert report["producer_ingress"] == "NOT_VERIFIED"
    assert report["claim_writeback"] == "NOT_VERIFIED"
    assert report["trading_authority"] is False
    rendered = json.dumps(report)
    for secret in ("do-not-export", "private-source-reference",
                   "synthetic-audit-id", "raw_price", "id-private"):
        assert secret not in rendered
    assert path.read_bytes() == before


def test_ephemeral_mount_is_blocked_even_for_valid_database(tmp_path, monkeypatch):
    path = tmp_path / "store.sqlite3"
    _store(path)
    monkeypatch.setattr(audit, "_path_allowed", lambda _: path)
    result = audit.observe(str(path), mountinfo=VOLATILE_MOUNT)
    assert result["status"] == "BLOCKED"
    assert result["backing"] == "EPHEMERAL_OR_UNKNOWN"
    assert result["audit_tail_digest"] is None


def test_wrong_schema_or_corrupt_db_is_blocked(tmp_path, monkeypatch):
    path = tmp_path / "invalid.sqlite3"
    _store(path, schema_version="0")
    monkeypatch.setattr(audit, "_path_allowed", lambda _: path)
    assert audit.observe(str(path), mountinfo=DISK_MOUNT)["status"] == "BLOCKED"
    path.write_bytes(b"this is not sqlite")
    assert audit.observe(str(path), mountinfo=DISK_MOUNT)["status"] == "BLOCKED"


def test_missing_symlink_and_unsafe_paths_never_create_database(tmp_path):
    absent = tmp_path / "absent.sqlite3"
    assert audit.observe(str(absent))["status"] == "BLOCKED"
    assert not absent.exists()
    real = tmp_path / "real.sqlite3"
    real.write_bytes(b"dummy")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(real)
    assert audit._path_allowed(str(link)) is None
    assert audit._path_allowed("../relative.sqlite3") is None
    assert audit._path_allowed("/run/ephemeral.sqlite3") is None
    assert audit._path_allowed("/tmp/file;cat /etc/passwd") is None


def test_mount_class_chooses_longest_nested_mount(tmp_path):
    path = tmp_path / "store.sqlite3"
    fake_mounts = (
        "10 1 0:1 / / rw - ext4 /dev/fake rw\n"
        f"11 10 0:2 / {tmp_path} rw - tmpfs tmpfs rw\n"
    )
    assert audit._mount_class(path, fake_mounts) == "EPHEMERAL_OR_UNKNOWN"
    assert audit._mount_class(path, DISK_MOUNT) == (
        "NON_VOLATILE_TYPE_OBSERVED_NOT_PROVEN"
    )
    assert audit._mount_class(
        path, "12 1 0:1 / / rw - unknownfs unknown rw\n",
    ) == "EPHEMERAL_OR_UNKNOWN"
    assert audit._mount_class(
        path, "13 1 0:1 / / rw - overlay overlay rw\n",
    ) == "EPHEMERAL_OR_UNKNOWN"


def test_parent_symlink_is_detected_independently_of_volatile_root(tmp_path):
    """Do not trust a requested path when its parent redirects elsewhere."""
    authority = tmp_path / "actual-disk"
    authority.mkdir()
    database = authority / "queue.sqlite3"
    database.write_bytes(b"fixture")
    alias = tmp_path / "alias"
    alias.symlink_to(authority, target_is_directory=True)

    assert audit._has_symlink_component(database) is False
    assert audit._has_symlink_component(alias / "queue.sqlite3") is True
    assert audit._path_allowed(str(alias / "queue.sqlite3")) is None


def test_observer_uses_one_sqlite_read_transaction():
    source = Path("scripts/audit_feedback_hub_ec2_readonly.py").read_text(
        encoding="utf-8",
    )
    marker = 'conn.execute("PRAGMA query_only=ON")'
    assert source.count(marker) == 1
    section = source.split(marker, 1)[1].split(
        "status_rows = conn.execute(", 1,
    )[0]
    assert 'conn.execute("BEGIN")' in section
    assert "PRAGMA journal_mode=WAL" not in source
