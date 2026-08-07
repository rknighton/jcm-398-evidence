import tempfile
import unittest
from pathlib import Path

from harness.common import load_json, load_jsonl
from harness.packet import build_summary
from harness.verify import verify_packet
from tests.packet_fixture import build_packet


class PacketIntegrationTests(unittest.TestCase):
    def test_synthetic_complete_packet_verifies_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            result = verify_packet(build_packet(Path(directory)))
            self.assertEqual("complete", result["verdict"])
            self.assertEqual(240, result["matrix_rows_observed"])
            self.assertEqual(21, result["controls_passed"])

    def test_summary_excludes_m1_no_results_and_separates_m10_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = build_packet(Path(directory))
            pairs = load_jsonl(packet / "paired.jsonl")
            controls = [load_json(packet / "controls" / f"C{number}.json") for number in range(1, 22)]
            first = next(item for item in pairs if item["arm"] == "matrix")
            first["metrics"]["m1_status"] = "no_results"
            first["metrics"]["m1_rank0_difference"] = None
            failures = load_jsonl(packet / "FAILURE-JOURNAL.jsonl")
            repairs = load_jsonl(packet / "REPAIR-JOURNAL.jsonl")
            summary = build_summary(pairs, controls, failures, repairs, run_id="synthetic-run")
            self.assertEqual(119, summary["counts"]["m1_rank0_difference"]["pair_denominator"])
            self.assertEqual(1, summary["counts"]["m1_rank0_difference"]["pair_excluded_no_results"])
            self.assertEqual(120, summary["m10"]["raw_cosine"]["pair_count"])
            self.assertEqual(60, summary["m10"]["hybrid_final"]["pair_count"])


if __name__ == "__main__":
    unittest.main()
