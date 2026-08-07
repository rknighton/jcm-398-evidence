import itertools
import random
import unittest

from harness.controls import synthetic_metric_controls, validate_external_control_evidence
from harness.metrics import compare_pair, inversion_count, numeric_summary


class MetricsTests(unittest.TestCase):
    def test_all_preregistered_synthetic_controls_pass(self):
        results = synthetic_metric_controls()
        self.assertEqual(10, len(results))
        self.assertTrue(all(item["passed"] for item in results), results)

    def test_m2_contains_m3_direction(self):
        result = compare_pair({"a": 3.0, "b": 2.0, "c": 1.0}, {"a": 3.0, "c": 2.0, "b": 1.0}, 2)
        self.assertTrue(result["m2_ordered_top_k_difference"])
        self.assertTrue(result["m3_membership_top_k_difference"])

    def test_fast_inversion_count_matches_bruteforce(self):
        randomizer = random.Random(398)
        for size in range(1, 12):
            ids = [f"s{i}" for i in range(size)]
            left = {item: randomizer.randrange(4) for item in ids}
            right = {item: randomizer.randrange(4) for item in ids}
            brute = 0
            for a, b in itertools.combinations(ids, 2):
                brute += (left[a] - left[b]) * (right[a] - right[b]) < 0
            self.assertEqual(brute, inversion_count(left, right, ids))

    def test_finite_zero_remains_eligible(self):
        self.assertEqual(0.0, numeric_summary([0.0, 2.0])["minimum"])

    def test_control_evidence_rejects_unknown_fields(self):
        with self.assertRaisesRegex(RuntimeError, "c1_evidence_keys"):
            validate_external_control_evidence("C1", {"lanes": {}, "attested": True})


if __name__ == "__main__":
    unittest.main()
