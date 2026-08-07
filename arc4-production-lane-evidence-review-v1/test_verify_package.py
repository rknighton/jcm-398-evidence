from __future__ import annotations

import hashlib
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import verify_package as verifier


verify = verifier.verify


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class VerifyPackageTests(unittest.TestCase):
    def make_package(self, content: bytes = b"review\n") -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "package"
        root.mkdir()
        (root / "REPORT.md").write_bytes(content)
        (root / "CHECKSUMS.sha256").write_text(
            f"{digest(content)}  REPORT.md\n", encoding="utf-8"
        )
        return root

    def test_valid_package_passes(self) -> None:
        self.assertEqual([], verify(self.make_package()))

    def test_tampering_fails(self) -> None:
        root = self.make_package()
        (root / "REPORT.md").write_text("changed\n", encoding="utf-8")
        self.assertIn("hash mismatch: REPORT.md", verify(root))

    def test_private_path_fails(self) -> None:
        content = b"C:\\Users\\Admin\\private\n"
        root = self.make_package(content)
        self.assertIn("private absolute path: REPORT.md", verify(root))

    def test_sha_substring_is_not_an_internal_task_id(self) -> None:
        content = b"sha256:9f019f7ac18e889f7953d57d1ead8f585c7f17d85c41cc66f72171169f50091a\n"
        self.assertEqual([], verify(self.make_package(content)))

    def test_headline_schema_mismatch_fails(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "INDEX.json").write_text(
            json.dumps({"schema_version": "wrong", "datasets": {}}),
            encoding="utf-8",
        )
        original_root = verifier.ROOT
        try:
            verifier.ROOT = root
            errors = verifier.verify_headline_claims()
        finally:
            verifier.ROOT = original_root
        self.assertIn(
            "headline mismatch: index schema: 'wrong' != "
            "'arc4-production-lane-evidence-review/v1'",
            errors,
        )

    def test_paired_gzip_reconstructs_original(self) -> None:
        root = self.make_package()
        packet = root / "evidence/comparison-v2/packet"
        packet.mkdir(parents=True)
        source = b'{"case":1}\n{"case":2}\n'
        compressed = gzip.compress(source, compresslevel=9, mtime=0)
        gzip_path = packet / "paired.jsonl.gz"
        gzip_path.write_bytes(compressed)
        metadata = {
            "source_bytes": len(source),
            "source_lines": 2,
            "source_sha256": digest(source),
            "compressed_bytes": len(compressed),
            "compressed_sha256": digest(compressed),
        }
        (packet / "paired.jsonl.gz.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        files = sorted(
            path for path in root.rglob("*") if path.is_file() and path.name != "CHECKSUMS.sha256"
        )
        (root / "CHECKSUMS.sha256").write_text(
            "".join(
                f"{digest(path.read_bytes())}  {path.relative_to(root).as_posix()}\n"
                for path in files
            ),
            encoding="utf-8",
        )
        self.assertEqual([], verify(root))


if __name__ == "__main__":
    unittest.main()
