import json
import csv
import tempfile
import unittest
from pathlib import Path

from harness.packet import build_manifest, decompose_original_matrix, materialize_full_rankings, score_vector_bytes


class PacketTests(unittest.TestCase):
    def test_score_vector_encoding_is_closed_and_canonical(self):
        payload = score_vector_bytes({"b": "0x1.0000000000000p-1", "a": "0x1.0000000000000p+0"}, expected_ids={"a", "b"})
        lines = payload.decode("utf-8").splitlines()
        self.assertEqual('{"schema":"arc4.full-score-vector/v1"}', lines[0])
        self.assertEqual("a", json.loads(lines[1])["symbol_id"])
        self.assertTrue(payload.endswith(b"\n"))

    def test_materialization_deduplicates_semantic_only_vector(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = Path(directory)
            full = packet / "raw" / "full-rankings"
            row = {"arm": "matrix", "row_id": "abc", "raw_cosine": {"a": "0x1.0000000000000p+0"}, "final_scores": {"a": "0x1.0000000000000p+0"}}
            result = materialize_full_rankings(row, full, expected_ids={"a"})
            self.assertEqual({"same_as": "raw_cosine"}, result["files"]["final"])
            self.assertEqual(1, len(list(full.glob("*.jsonl"))))

    def test_manifest_excludes_its_circular_surfaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence.txt").write_text("evidence\n", encoding="utf-8")
            (root / "MANIFEST.json").write_text("old", encoding="utf-8")
            (root / "MANIFEST.sha256").write_text("old", encoding="utf-8")
            (root / "verification.txt").write_text("old", encoding="utf-8")
            manifest, digest = build_manifest(root)
            self.assertEqual(["evidence.txt"], [item["path"] for item in manifest["files"]])
            self.assertEqual(64, len(digest))

    def test_original_matrix_is_recomputed_not_transcribed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "measurements.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["row_id", "case_id", "pair_id", "mode", "row_status"])
                writer.writeheader()
                ordinal = 0
                for case in range(24):
                    for repetition in range(5):
                        pair = f"case-{case}:r{repetition}"
                        for mode in ("a", "b", "c"):
                            writer.writerow({"row_id": f"row-{ordinal}", "case_id": f"case-{case}", "pair_id": pair, "mode": mode, "row_status": "retained"})
                            ordinal += 1
            value = decompose_original_matrix(source)
            self.assertEqual(360, value["rows"])
            self.assertEqual(120, value["pair_ids"])


if __name__ == "__main__":
    unittest.main()
