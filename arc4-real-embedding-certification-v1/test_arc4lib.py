from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

import arc4lib


class DeterminismTests(unittest.TestCase):
    def test_tie_break_is_independent_of_insertion_order(self) -> None:
        scores = [0.5, 0.5, 0.25]
        ids = ["zeta", "alpha", "middle"]
        self.assertEqual(arc4lib.insertion_order_top(scores, 2), [0, 1])
        self.assertEqual(arc4lib.deterministic_top(scores, ids, 2), [1, 0])

        reverse = [1, 0, 2]
        reversed_scores = [scores[index] for index in reverse]
        reversed_ids = [ids[index] for index in reverse]
        historical = [reversed_ids[index] for index in arc4lib.insertion_order_top(reversed_scores, 2)]
        deterministic = [reversed_ids[index] for index in arc4lib.deterministic_top(reversed_scores, reversed_ids, 2)]
        self.assertEqual(historical, ["alpha", "zeta"])
        self.assertEqual(deterministic, ["alpha", "zeta"])


class BoundTests(unittest.TestCase):
    def test_float32_bounds_contain_exact_scores(self) -> None:
        random = np.random.default_rng(20260802)
        matrix = random.normal(size=(128, 384)).astype(np.float32)
        query = random.normal(size=384).astype(np.float32)
        estimates, lower, upper = arc4lib.float32_scores_and_bounds(matrix, query)
        exact = np.asarray(
            [arc4lib.exact_cosine(query.tolist(), row.tolist()) for row in matrix]
        )
        self.assertTrue(np.all(lower <= exact))
        self.assertTrue(np.all(exact <= upper))
        self.assertTrue(np.all(np.isfinite(estimates)))

    def test_zero_vectors_are_exactly_zero(self) -> None:
        matrix = np.zeros((3, 4), dtype=np.float32)
        query = np.ones(4, dtype=np.float32)
        estimates, lower, upper = arc4lib.float32_scores_and_bounds(matrix, query)
        np.testing.assert_array_equal(estimates, np.zeros(3))
        np.testing.assert_array_equal(lower, np.zeros(3))
        np.testing.assert_array_equal(upper, np.zeros(3))

    def test_dimension_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimensions do not match"):
            arc4lib.float32_scores_and_bounds(
                np.ones((2, 3), dtype=np.float32), np.ones(4, dtype=np.float32)
            )


class LaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = np.asarray(
            [[1.0, 0.0], [0.999999, 0.001], [0.0, 1.0]], dtype=np.float32
        )
        self.query = np.asarray([1.0, 0.0], dtype=np.float32)
        self.ids = ["b", "a", "c"]
        self.lexical = [0.0, 0.0, 0.0]

    def execute(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "matrix": self.matrix,
            "query": self.query,
            "symbol_ids": self.ids,
            "lexical_base": self.lexical,
            "semantic_weight": 1.0,
            "top_k": 2,
            "mode": "float32_certified_candidate",
            "max_rescore_fraction": 1.0,
        }
        arguments.update(overrides)
        return arc4lib.execute_mode(**arguments)

    def test_candidate_matches_deterministic_exact_top(self) -> None:
        result = self.execute()
        self.assertEqual([self.ids[index] for index in result["top"]], ["b", "a"])

    def test_forced_exact_fallback_is_explicit(self) -> None:
        result = self.execute(mode="bounded_exact_fallback")
        self.assertEqual(result["lane_selected"], "bounded_exact_fallback")
        self.assertEqual(result["fallback_reason"], "forced_exact_fallback_mode")
        self.assertEqual(result["rescored_count"], len(self.ids))

    def test_memory_cap_refusal_falls_back(self) -> None:
        result = self.execute(matrix_max_bytes=1)
        self.assertEqual(result["lane_selected"], "bounded_exact_fallback")
        self.assertEqual(result["fallback_reason"], "memory_cap_refusal")

    def test_missing_numpy_falls_back(self) -> None:
        with mock.patch.object(
            arc4lib, "float32_scores_and_bounds", side_effect=ImportError("missing")
        ):
            result = self.execute()
        self.assertEqual(result["fallback_reason"], "numpy_unavailable")

    def test_allocation_failure_falls_back(self) -> None:
        with mock.patch.object(
            arc4lib, "float32_scores_and_bounds", side_effect=MemoryError("allocation")
        ):
            result = self.execute()
        self.assertEqual(result["fallback_reason"], "allocation_failure")

    def test_certification_fraction_limit_falls_back(self) -> None:
        result = self.execute(top_k=1, max_rescore_fraction=0.0)
        self.assertEqual(result["fallback_reason"], "certification_fraction_limit")

    def test_score_case_reconciles_all_certified_buckets(self) -> None:
        result = arc4lib.score_case(
            matrix=self.matrix,
            query=self.query,
            symbol_ids=self.ids,
            lexical_base=self.lexical,
            semantic_weight=1.0,
            top_k=2,
            mode="float32_certified_candidate",
            max_rescore_fraction=1.0,
        )
        self.assertTrue(result["canonical_parity"])
        self.assertEqual(result["interval_violation_count"], 0)
        self.assertEqual(
            result["total_certified_count"],
            result["near_tie_count"]
            + result["genuine_disagreement_count"]
            + result["other_certified_count"],
        )


if __name__ == "__main__":
    unittest.main()
