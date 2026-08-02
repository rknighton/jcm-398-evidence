"""Adversarial tests for the Arc 4 release-asset tooling."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from release_asset import AssetError, audit_database, safe_member, sha256_file


class SafeMemberTests(unittest.TestCase):
    def test_accepts_expected_member(self) -> None:
        self.assertTrue(safe_member("indexes/example.db"))

    def test_rejects_parent_traversal(self) -> None:
        self.assertFalse(safe_member("../example.db"))

    def test_rejects_absolute_member(self) -> None:
        self.assertFalse(safe_member("/indexes/example.db"))


class DatabaseAuditTests(unittest.TestCase):
    def make_database(self, path: Path, text: str) -> dict[str, object]:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE symbol_embeddings (symbol_id TEXT PRIMARY KEY, embedding BLOB)"
            )
            connection.execute(
                "INSERT INTO symbol_embeddings VALUES (?, ?)", ("symbol", b"\x00" * 8)
            )
            connection.execute("CREATE TABLE meta (key TEXT, value TEXT)")
            connection.execute("INSERT INTO meta VALUES ('source', ?)", (text,))
            connection.commit()
        finally:
            connection.close()
        return {
            "working_database_sha256": sha256_file(path),
            "embedding_vector_count": 1,
            "embedding_meta": {"embed_dimension": "2"},
        }

    def test_accepts_integral_path_safe_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            path = Path(temporary_name) / "index.db"
            expected = self.make_database(path, "public source")
            result = audit_database(path, expected)
            self.assertEqual(result["sqlite_integrity"], "ok")
            self.assertEqual(result["local_path_scan"], "PASS")

    def test_rejects_machine_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            path = Path(temporary_name) / "index.db"
            expected = self.make_database(path, "C:/Users/Admin/private")
            with self.assertRaises(AssetError):
                audit_database(path, expected)


if __name__ == "__main__":
    unittest.main()
