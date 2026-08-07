import unittest

from harness.cases import QUERY_IDS, generate_frozen_cases, validate_frozen_cases


def query_record(query_id, index):
    semantic_only = index < 2
    weight = 1.0 if semantic_only else 0.5
    top_k = 10 if index in (0, 2) else 25
    text = query_id.replace("_", " ")
    return {
        "query": text, "query_embedding_sha256": f"{index + 1:x}" * 64,
        "serialized_args": {"query": text, "semantic_only": semantic_only, "semantic_weight": weight, "max_results": top_k, "detail_level": "compact", "debug": False},
    }


class FrozenCasesTests(unittest.TestCase):
    def setUp(self):
        self.corpora = [
            {"name": name, "working_database_sha256": character * 64, "candidate_ids": ["a", "b"]}
            for name, character in (("django", "a"), ("fastapi", "b"), ("jcodemunch", "c"))
        ]
        self.queries = {query_id: query_record(query_id, index) for index, query_id in enumerate(QUERY_IDS)}

    def test_exact_matrix_and_order_balance(self):
        value = generate_frozen_cases(run_id="run-v2", corpora=self.corpora, queries=self.queries)
        validate_frozen_cases(value)
        self.assertEqual(132, len(value["case_executions"]))
        self.assertEqual(264, len(value["planned_rows"]))
        matrix = [row for row in value["planned_rows"] if row["arm"] == "matrix"]
        self.assertEqual(240, len(matrix))
        self.assertEqual({"numpy_present", "numpy_absent"}, {row["lane"] for row in matrix})

    def test_generation_is_byte_deterministic(self):
        first = generate_frozen_cases(run_id="run-v2", corpora=self.corpora, queries=self.queries)
        second = generate_frozen_cases(run_id="run-v2", corpora=self.corpora, queries=self.queries)
        self.assertEqual(first, second)

    def test_query_expansion_fails_closed(self):
        self.queries["invented"] = {"query": "no", "query_embedding_sha256": "f" * 64}
        with self.assertRaisesRegex(RuntimeError, "query_set"):
            generate_frozen_cases(run_id="run-v2", corpora=self.corpora, queries=self.queries)


if __name__ == "__main__":
    unittest.main()
