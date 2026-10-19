"""Offline tests for Round14 artifact gate; no market data or network required."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "research" / "round14_artifact_gate.py"
spec = importlib.util.spec_from_file_location("round14_artifact_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ArtifactGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = [name for name in gate.REQUIRED if not name.endswith(".sha256")]
        for name in self.files:
            (self.root / name).write_text("fixture:" + name, encoding="utf-8")
        self.write_manifest(self.files)

    def write_manifest(self, names):
        rows = []
        for name in names:
            p = self.root / name
            rows.append(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + name)
        (self.root / "round13_artifact_manifest.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def test_complete_hash_inventory_not_equal_engine_parity(self):
        result = gate.verify(self.root)
        self.assertTrue(result["inventory_complete"])
        self.assertTrue(result["manifest_valid"])
        self.assertEqual(result["gate"], "BLOCKED")
        self.assertFalse(result["engine_source_verified"])
        self.assertFalse(result["ohlc_inputs_verified"])

    def test_missing_manifest_entry_fails(self):
        self.write_manifest(self.files[:-1])
        result = gate.verify(self.root)
        self.assertFalse(result["manifest_valid"])
        self.assertEqual(result["manifest_coverage"], [self.files[-1]])

    def test_tampered_file_fails(self):
        (self.root / self.files[0]).write_text("tampered", encoding="utf-8")
        self.assertFalse(gate.verify(self.root)["manifest_valid"])

    def test_missing_required_file_fails(self):
        (self.root / self.files[0]).unlink()
        result = gate.verify(self.root)
        self.assertFalse(result["inventory_complete"])
        self.assertFalse(result["manifest_valid"])

    def test_duplicate_manifest_entry_fails(self):
        manifest = self.root / "round13_artifact_manifest.sha256"
        first = manifest.read_text(encoding="utf-8").splitlines()[0]
        with manifest.open("a", encoding="utf-8") as f:
            f.write(first + "\n")
        self.assertFalse(gate.verify(self.root)["manifest_valid"])

    def test_parent_directory_escape_fails(self):
        manifest = self.root / "round13_artifact_manifest.sha256"
        with manifest.open("a", encoding="utf-8") as f:
            f.write("0" * 64 + "  ../outside.csv\n")
        self.assertFalse(gate.verify(self.root)["manifest_valid"])


if __name__ == "__main__":
    unittest.main()
