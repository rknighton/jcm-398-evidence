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
    """Exercises the verifier's machinery on synthetic packages.

    These do not run the headline recomputation against this package's real data.
    `require_release_layout` in verify_package.verify() is false for any root other
    than the package directory, so `verify_headline_claims` is skipped here by
    design. Running `py -3 -B verify_package.py` is what checks the real data.
    """

    def make_package(self, content: bytes = b"review\n", disclosure: dict | None = None) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "package"
        root.mkdir()
        (root / "REPORT.md").write_bytes(content)
        files = {"REPORT.md"}
        if disclosure is not None:
            body = json.dumps(disclosure, indent=2).encode() + b"\n"
            (root / "LOCAL-PATH-DISCLOSURE.json").write_bytes(body)
            files.add("LOCAL-PATH-DISCLOSURE.json")
        (root / "CHECKSUMS.sha256").write_text(
            "".join(
                f"{digest((root / name).read_bytes())}  {name}\n" for name in sorted(files)
            ),
            encoding="utf-8",
        )
        return root

    def empty_disclosure(self) -> dict:
        return {
            "schema_version": "arc4.local-path-disclosure/v1",
            "file_count": 0,
            "occurrence_count": 0,
            "files": {},
        }

    def test_valid_package_passes(self) -> None:
        self.assertEqual([], verify(self.make_package(disclosure=self.empty_disclosure())))

    def test_tampering_fails(self) -> None:
        root = self.make_package(disclosure=self.empty_disclosure())
        (root / "REPORT.md").write_text("changed\n", encoding="utf-8")
        self.assertIn("hash mismatch: REPORT.md", verify(root))

    def test_missing_disclosure_record_fails(self) -> None:
        root = self.make_package()
        errors = verify(root)
        self.assertTrue(
            any("missing required disclosure record" in error for error in errors), errors
        )

    def test_undeclared_raw_private_path_fails(self) -> None:
        content = b"C:\\Users\\Admin\\private\n"
        root = self.make_package(content, disclosure=self.empty_disclosure())
        errors = verify(root)
        self.assertTrue(any(error.startswith("undeclared local path: REPORT.md") for error in errors), errors)

    def test_undeclared_json_escaped_private_path_fails(self) -> None:
        """The escaped form is the only form the real JSON records use.

        The original check searched for a single-backslash literal and could not
        see this, which is why 79 files shipped undetected.
        """
        content = b'{"root": "C:\\\\Users\\\\Admin\\\\Documents"}\n'
        root = self.make_package(content, disclosure=self.empty_disclosure())
        errors = verify(root)
        self.assertTrue(any(error.startswith("undeclared local path: REPORT.md") for error in errors), errors)

    def test_lowercase_and_file_url_private_paths_fail(self) -> None:
        content = b"file:///c:/users/admin/x and file:///C:/Users/Admin/y\n"
        root = self.make_package(content, disclosure=self.empty_disclosure())
        errors = verify(root)
        self.assertTrue(any(error.startswith("undeclared local path: REPORT.md") for error in errors), errors)

    def test_declared_private_path_passes_with_exact_counts(self) -> None:
        content = b'{"root": "C:\\\\Users\\\\Admin\\\\Documents"}\n'
        disclosure = {
            "schema_version": "arc4.local-path-disclosure/v1",
            "file_count": 1,
            "occurrence_count": 1,
            "files": {"REPORT.md": {"windows_research_root": 1}},
        }
        self.assertEqual([], verify(self.make_package(content, disclosure=disclosure)))

    def test_stale_declaration_fails(self) -> None:
        disclosure = {
            "schema_version": "arc4.local-path-disclosure/v1",
            "file_count": 1,
            "occurrence_count": 1,
            "files": {"REPORT.md": {"windows_research_root": 1}},
        }
        root = self.make_package(b"clean\n", disclosure=disclosure)
        errors = verify(root)
        self.assertTrue(
            any(error.startswith("stale local-path declaration") for error in errors), errors
        )

    def test_declared_count_drift_fails(self) -> None:
        content = b'{"a": "C:\\\\Users\\\\Admin", "b": "C:\\\\Users\\\\Admin"}\n'
        disclosure = {
            "schema_version": "arc4.local-path-disclosure/v1",
            "file_count": 1,
            "occurrence_count": 1,
            "files": {"REPORT.md": {"windows_research_root": 1}},
        }
        errors = verify(self.make_package(content, disclosure=disclosure))
        self.assertTrue(any("local-path count changed" in error for error in errors), errors)

    def test_em_dash_is_rejected_in_a_non_text_extension(self) -> None:
        """The hygiene scan reads bytes, so extension is irrelevant."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "package"
        root.mkdir()
        # Spelled in bytes so this test file does not itself contain the character.
        (root / "notes.log").write_bytes(b"a " + b"\xe2\x80\x94" + b" b\n")
        (root / "LOCAL-PATH-DISCLOSURE.json").write_text(
            json.dumps(self.empty_disclosure()), encoding="utf-8"
        )
        names = ["LOCAL-PATH-DISCLOSURE.json", "notes.log"]
        (root / "CHECKSUMS.sha256").write_text(
            "".join(f"{digest((root / n).read_bytes())}  {n}\n" for n in names), encoding="utf-8"
        )
        self.assertIn("forbidden Unicode em dash: notes.log", verify(root))

    def test_sha_substring_is_not_an_internal_task_id(self) -> None:
        content = b"sha256:9f019f7ac18e889f7953d57d1ead8f585c7f17d85c41cc66f72171169f50091a\n"
        self.assertEqual([], verify(self.make_package(content, disclosure=self.empty_disclosure())))

    def test_headline_schema_mismatch_fails(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "INDEX.json").write_text(
            json.dumps({"schema_version": "wrong", "datasets": {}}), encoding="utf-8"
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
        root = self.make_package(disclosure=self.empty_disclosure())
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
        (packet / "paired.jsonl.gz.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.rewrite_manifest(root)
        self.assertEqual([], verify(root))

    def test_paired_gzip_hash_mismatch_fails(self) -> None:
        root = self.make_package(disclosure=self.empty_disclosure())
        packet = root / "evidence/comparison-v2/packet"
        packet.mkdir(parents=True)
        source = b'{"case":1}\n'
        compressed = gzip.compress(source, compresslevel=9, mtime=0)
        (packet / "paired.jsonl.gz").write_bytes(compressed)
        metadata = {
            "source_bytes": len(source),
            "source_lines": 1,
            "source_sha256": digest(b"something else"),
            "compressed_bytes": len(compressed),
            "compressed_sha256": digest(compressed),
        }
        (packet / "paired.jsonl.gz.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.rewrite_manifest(root)
        self.assertIn("paired gzip source hash mismatch", verify(root))

    def test_gzip_without_metadata_is_an_error_not_a_skip(self) -> None:
        """A half-present pair is exactly what a silent skip would hide.

        Absence of both halves is legitimate outside the release layout, where
        no gzip-stored dataset need exist. A gzip with no metadata beside it is
        never legitimate, because nothing would then check its reconstruction.
        """
        root = self.make_package(disclosure=self.empty_disclosure())
        packet = root / "evidence/comparison-v2/packet"
        packet.mkdir(parents=True)
        (packet / "paired.jsonl.gz").write_bytes(gzip.compress(b'{"case":1}\n', mtime=0))
        self.rewrite_manifest(root)
        self.assertIn("gzip present without metadata: paired.jsonl.gz", verify(root))

    def test_release_layout_requires_the_paired_dataset(self) -> None:
        """In the real package the dataset is mandatory, so its absence must fail."""
        root = self.make_package(disclosure=self.empty_disclosure())
        original = verifier.PACKAGE_ROOT
        try:
            verifier.PACKAGE_ROOT = root.resolve()
            errors = verify(root)
        finally:
            verifier.PACKAGE_ROOT = original
        self.assertTrue(
            any(error.startswith("missing paired gzip metadata") for error in errors), errors
        )

    def make_replay(self, root: Path, lane_rows: dict[str, list[tuple[str, str, str]]]) -> Path:
        """Minimal replay tree. lane_rows maps corpus to (query_id, corpus, vector_sha256)."""
        replay = root / "replay"
        (replay / "raw").mkdir(parents=True)
        for lane in ("numpy", "python"):
            for corpus in ("django", "fastapi", "jcodemunch"):
                lines = [
                    json.dumps({"lane": lane, "corpus": corpus, "vectorised": lane == "numpy"})
                ]
                for query_id, row_corpus, vector in lane_rows.get(corpus, []):
                    lines.append(json.dumps({"query_id": query_id, "vector_sha256": vector}))
                (replay / "raw" / f"{lane}-{corpus}.jsonl").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )
        return replay

    def test_replay_reconciles_to_the_shipped_query_corpus(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "provider-text.jsonl"
        source.write_text(
            "\n".join(
                json.dumps({"query_id": f"text-{n:05d}", "corpus_seed": "django", "vector_sha256": f"v{n}"})
                for n in range(3)
            )
            + "\n",
            encoding="utf-8",
        )
        rows = [(f"text-{n:05d}", "django", f"v{n}") for n in range(3)]
        replay = self.make_replay(root, {"django": rows})
        self.assertEqual([], verifier.reconcile_replay_to_source(source, replay))

    def test_replay_with_a_substituted_query_fails(self) -> None:
        """Comparing the two lanes to each other cannot catch this.

        Both lanes agree perfectly; they simply replayed a query the shipped
        corpus does not contain, and omitted one it does.
        """
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "provider-text.jsonl"
        source.write_text(
            "\n".join(
                json.dumps({"query_id": f"text-{n:05d}", "corpus_seed": "django", "vector_sha256": f"v{n}"})
                for n in range(3)
            )
            + "\n",
            encoding="utf-8",
        )
        rows = [("text-00000", "django", "v0"), ("text-00001", "django", "v1"),
                ("text-09999", "django", "v9999")]
        replay = self.make_replay(root, {"django": rows})
        errors = verifier.reconcile_replay_to_source(source, replay)
        self.assertTrue(any("shipped query never replayed: text-00002" in e for e in errors), errors)
        self.assertTrue(
            any("replayed a query absent from the shipped corpus: text-09999" in e for e in errors),
            errors,
        )

    def test_replay_with_a_swapped_vector_hash_fails(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "provider-text.jsonl"
        source.write_text(
            json.dumps({"query_id": "text-00000", "corpus_seed": "django", "vector_sha256": "v0"})
            + "\n",
            encoding="utf-8",
        )
        replay = self.make_replay(root, {"django": [("text-00000", "django", "tampered")]})
        errors = verifier.reconcile_replay_to_source(source, replay)
        self.assertTrue(any("shipped as" in e for e in errors), errors)

    def rewrite_manifest(self, root: Path) -> None:
        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != "CHECKSUMS.sha256"
        )
        (root / "CHECKSUMS.sha256").write_text(
            "".join(
                f"{digest(path.read_bytes())}  {path.relative_to(root).as_posix()}\n"
                for path in files
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
